from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tools.brain import history, memory, observer


def extract_model(store, kind, rows):
    assert kind == "observer"
    return {"decisions": [{
        "id": row["id"], "decision": "extract", "reason": "", "observations": [{
            "observation": "Verify a real result before claiming completion.",
            "evidence": "The user explicitly requested verification of outputs.",
            "non_sensitive": True, "durable": True,
        }],
    } for row in rows]}


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "AGENTS.md").write_text("Fixture", encoding="utf-8")
        self.source = self.root / "source.db"
        with sqlite3.connect(self.source) as db:
            db.executescript("""
                CREATE TABLE sessions(id TEXT PRIMARY KEY,repository TEXT);
                CREATE TABLE turns(id INTEGER PRIMARY KEY,session_id TEXT,turn_index INTEGER,
                    user_message TEXT,assistant_response TEXT,timestamp TEXT,
                    UNIQUE(session_id,turn_index));
            """)
        self.store = memory.Store(self.root)
        history.configure(self.store, self.source, ["*"], 30, confirmed=True)
        observer.configure(self.store, confirmed=True)

    def tearDown(self):
        self.temp.cleanup()

    def turn(self, index=0, message="Always verify the real outputs. REQUEST_SENTINEL",
             repository="fixture/repo", session="session-a"):
        with sqlite3.connect(self.source) as db:
            db.execute("INSERT OR IGNORE INTO sessions VALUES (?,?)", (session, repository))
            db.execute("INSERT INTO turns(session_id,turn_index,user_message,assistant_response,timestamp)"
                       " VALUES (?,?,?,?,?)", (session, index, message, "ASSISTANT_CODE_SENTINEL",
                           (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()))
        history.collect(self.store)

    def test_unattended_extraction_and_replay(self):
        self.turn()
        result = observer.run(self.store, extract_model)
        self.assertEqual(result["extracted_references"], 1)
        self.assertEqual(result["candidate_records"], 1)
        self.assertEqual(len(self.store.rows("pending")), 1)
        self.assertEqual(observer.run(self.store, extract_model)["model_inputs"], 0)
        for path in self.store.local.rglob("*"):
            if path.is_file():
                self.assertNotIn(b"REQUEST_SENTINEL", path.read_bytes())
                self.assertNotIn(b"ASSISTANT_CODE_SENTINEL", path.read_bytes())

    def test_protected_sources_and_sensitive_inputs_never_reach_model(self):
        self.turn(session="work", repository="Collection/Team/private")
        for index, text in enumerate((
            "Always verify ```source code```",
            "Always verify https://example.test/private",
            "Always verify my password=secret",
            "希望保存我的身份证信息",
            "以后请记录我的密码",
            "我的总投入是三万元，应该怎么办",
            "Always verify before saving my resume",
            "Verify " + "x" * 4001,
        )):
            self.turn(index=index, session="private-data", message=text)
        def unexpected(*args):
            self.fail("Protected data reached the model")
        result = observer.run(self.store, unexpected)
        self.assertEqual(result["held_for_review"], 9)
        self.assertEqual(result["model_inputs"], 0)
        self.assertEqual(len(history.list_pending(self.store, state="needs_review")), 9)
        self.assertEqual(self.store.rows("pending"), [])

    def test_automation_and_one_time_continuation_are_not_evidence(self):
        for index, text in enumerate((
            "# Scheduled workflow-memory observer\nworkflow",
            "# Weekly workflow-memory reviewer\nworkflow",
            "[Scheduled prompt #4]\nverify workflow",
            "<system_notification>verify</system_notification>",
            "<skill-context name='fixture'>verify",
            "<system-reminder>verify workflow</system-reminder>",
            "<environment_context>verify workflow</environment_context>",
            "<user_instructions>verify workflow</user_instructions>",
            "请继续",
        )):
            self.turn(index=index, message=text)
        def unexpected(*args):
            self.fail("Automation reached the model")
        self.assertEqual(observer.run(self.store, unexpected)["dismissed"], 9)
        self.assertEqual(self.store.rows("pending"), [])

    def test_malformed_model_batch_does_not_consume_any_input(self):
        self.turn()
        self.turn(index=1, message="Please verify https://example.test/private")
        def incomplete(store, kind, rows):
            return {"decisions": []}
        with self.assertRaisesRegex(ValueError, "Every observer input"):
            observer.run(self.store, incomplete)
        self.assertEqual(len(history.list_pending(self.store)), 2)
        self.assertEqual(self.store.rows("pending"), [])
        self.assertEqual(self.store.status()["recent_runs"][0]["state"], "failed")

    def test_invalid_output_attestation_and_content_fail_closed(self):
        self.turn()
        for field, value in (("non_sensitive", False), ("evidence", "Read https://example.test/private")):
            def bad(store, kind, rows):
                result = extract_model(store, kind, rows)
                result["decisions"][0]["observations"][0][field] = value
                return result
            with self.assertRaises(ValueError):
                observer.run(self.store, bad)
        self.assertEqual(len(history.list_pending(self.store)), 1)
        self.assertEqual(self.store.rows("pending"), [])

    def test_changed_source_after_inference_rolls_back(self):
        self.turn()
        def changing(store, kind, rows):
            with sqlite3.connect(self.source) as db:
                db.execute("UPDATE turns SET user_message='Verify the revised result'")
            return extract_model(store, kind, rows)
        with self.assertRaisesRegex(ValueError, "changed"):
            observer.run(self.store, changing)
        self.assertEqual(self.store.rows("pending"), [])
        self.assertEqual(len(history.list_pending(self.store)), 1)
        history.collect(self.store)
        self.assertEqual(observer.run(self.store, extract_model)["candidate_records"], 1)

    def test_model_failure_is_visible_and_recoverable(self):
        self.turn()
        def failed(*args):
            raise RuntimeError("Copilot timed out; no memory decisions applied")
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            observer.run(self.store, failed)
        self.assertEqual(self.store.status()["recent_runs"][0]["state"], "failed")
        self.assertEqual(len(history.list_pending(self.store)), 1)
        self.assertEqual(observer.run(self.store, extract_model)["candidate_records"], 1)

    def test_bounded_batches_and_actual_insert_counts(self):
        for index in range(observer.MAX_REFERENCES + 1):
            self.turn(index=index)
        result = observer.run(self.store, extract_model)
        self.assertEqual(result["model_inputs"], observer.MAX_REFERENCES)
        self.assertEqual(result["candidate_records"], 1)
        self.assertEqual(result["pending_references"], 1)
        self.assertEqual(observer.run(self.store, extract_model)["candidate_records"], 0)

    def test_model_sensitive_disposition_is_held_not_accepted(self):
        self.turn()
        def held(store, kind, rows):
            return {"decisions": [{
                "id": row["id"], "decision": "dismiss", "observations": [], "reason": "sensitive",
            } for row in rows]}
        self.assertEqual(observer.run(self.store, held)["held_for_review"], 1)
        ref = history.list_pending(self.store, state="needs_review")[0]
        payload = {"observations": extract_model(None, "observer", [{"id": "fixture"}])["decisions"][0]["observations"]}
        history.resolve(self.store, ref["id"], "distilled", payload, confirmed=True)
        self.assertEqual(len(self.store.rows("pending")), 1)

    def test_disabled_observer_and_authorization(self):
        with self.assertRaises(ValueError):
            observer.configure(self.store)
        config = observer.load_config(self.store)
        config["enabled"] = False
        memory.atomic_write(self.store.local / "observer.json", json.dumps(config))
        self.assertEqual(observer.run(self.store, extract_model)["state"], "skipped")

    def test_source_switch_requires_reconfiguration(self):
        self.turn()
        config = observer.load_config(self.store)
        config["history_origins"] = ["wrong-origin"]
        memory.atomic_write(self.store.local / "observer.json", json.dumps(config))
        with self.assertRaisesRegex(ValueError, "source changed"):
            observer.run(self.store, extract_model)

    def test_exclusive_worker_lock(self):
        with memory.worker_lock(self.store.local):
            with self.assertRaisesRegex(RuntimeError, "Another memory worker"):
                observer.run(self.store, extract_model)


if __name__ == "__main__":
    unittest.main()
