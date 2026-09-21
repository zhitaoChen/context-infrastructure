from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from tools.brain import history, memory


def observation(text="Validate a real end-to-end sample before scaling."):
    return {
        "observations": [{
            "observation": text, "evidence": "The user explicitly confirmed this reusable workflow.",
            "non_sensitive": True, "durable": True,
        }],
    }


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "AGENTS.md").write_text("Fixture", encoding="utf-8")
        self.source = self.root / "history-source.db"
        with sqlite3.connect(self.source) as db:
            db.executescript("""
                CREATE TABLE sessions(id TEXT PRIMARY KEY,repository TEXT);
                CREATE TABLE turns(id INTEGER PRIMARY KEY,session_id TEXT,turn_index INTEGER,
                    user_message TEXT,assistant_response TEXT,timestamp TEXT,
                    UNIQUE(session_id,turn_index));
            """)
        self.store = memory.Store(self.root)
        history.configure(self.store, self.source, ["*"], 30, confirmed=True)

    def tearDown(self):
        self.temp.cleanup()

    def turn(self, session="session-a", index=0, repository="fixture/project",
             message="PRIVATE_RAW_SENTINEL", assistant="UNVERIFIED_ASSISTANT_SENTINEL",
             age=1, stamp=None):
        stamp = stamp or (datetime.now(timezone.utc) - timedelta(days=age)).isoformat()
        with sqlite3.connect(self.source) as db:
            db.execute("INSERT OR IGNORE INTO sessions VALUES (?,?)", (session, repository))
            db.execute("INSERT INTO turns(session_id,turn_index,user_message,assistant_response,timestamp)"
                       " VALUES (?,?,?,?,?)", (session, index, message, assistant, stamp))

    def refs(self):
        return history.list_pending(self.store, 100)

    def test_collect_is_readonly_reference_only_and_never_calls_model(self):
        self.turn()
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        with mock.patch.object(memory, "call_copilot", side_effect=AssertionError("No model allowed")):
            result = history.collect(self.store)
        self.assertEqual(result["queued"], 1)
        self.assertEqual(before, hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(self.store.rows("pending"), [])
        for path in self.store.local.rglob("*"):
            if path.is_file():
                self.assertNotIn(b"PRIVATE_RAW_SENTINEL", path.read_bytes())
                self.assertNotIn(b"UNVERIFIED_ASSISTANT_SENTINEL", path.read_bytes())
        self.assertEqual(set(self.refs()[0]),
                         {"id", "session_id", "turn_index", "turn_time", "state", "reason"})
        with history.source_connection(history.load_config(self.store)) as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("DELETE FROM turns")

    def test_scope_backfill_and_incomplete_turn_window(self):
        self.turn()
        self.turn(session="other", repository="other/repo")
        self.turn(session="unknown", repository=None)
        self.turn(session="too-old", age=31)
        self.turn(session="active", age=0)
        history.configure(self.store, self.source, ["FIXTURE/PROJECT"], 30,
                          confirmed=True, replace=True)
        self.assertEqual(history.collect(self.store)["queued"], 1)
        self.assertEqual(self.refs()[0]["session_id"], "session-a")

    def test_all_repositories_includes_new_repositories(self):
        self.turn()
        history.collect(self.store)
        self.turn(session="new-project", repository="new/repo")
        self.assertEqual(history.collect(self.store)["queued"], 1)
        self.assertEqual(len(self.refs()), 2)

    def test_mixed_sqlite_and_iso_timestamps(self):
        stamp = datetime.now(timezone.utc) - timedelta(days=1)
        self.turn(stamp=stamp.strftime("%Y-%m-%d %H:%M:%S"))
        self.turn(index=1, stamp=stamp.isoformat().replace("+00:00", "Z"))
        self.assertEqual(history.collect(self.store)["queued"], 2)

    def test_resume_bounded_passes_and_idempotent_rescan(self):
        for index in range(5):
            self.turn(index=index)
        self.assertTrue(history.collect(self.store, 2)["more"])
        self.assertTrue(history.collect(self.store, 2)["more"])
        for _ in range(5):
            if not history.collect(self.store, 2)["more"]:
                break
        else:
            self.fail("Bounded scan did not finish")
        self.assertEqual(len(self.refs()), 5)
        self.assertEqual(history.collect(self.store)["queued"], 0)

    def test_appended_turns_take_priority_over_old_reconciliation(self):
        for index in range(5):
            self.turn(index=index)
        history.collect(self.store)
        self.turn(index=5)
        result = history.collect(self.store, 1)
        self.assertEqual(result["queued"], 1)
        self.assertEqual(result["new_scanned"], 1)
        self.assertEqual(result["reconciled"], 0)
        self.assertIn(5, {ref["turn_index"] for ref in self.refs()})

    def test_source_replacement_with_lower_ids_does_not_strand_cursor(self):
        for index in range(5):
            self.turn(index=index)
        history.collect(self.store, 2)
        with sqlite3.connect(self.source) as db:
            db.execute("DELETE FROM turns")
        self.turn(session="replacement")
        self.assertEqual(history.collect(self.store)["queued"], 1)
        self.assertIn("replacement", {ref["session_id"] for ref in self.refs()})

    def test_late_old_id_and_changed_content_are_reconciled(self):
        self.turn()
        self.turn(index=1, age=0)
        history.collect(self.store)
        old = self.refs()[0]["id"]
        with sqlite3.connect(self.source) as db:
            db.execute("UPDATE turns SET assistant_response='Completed response' WHERE turn_index=0")
            db.execute("UPDATE turns SET timestamp=? WHERE turn_index=1",
                       ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),))
        result = history.collect(self.store)
        self.assertEqual(result["queued"], 2)
        self.assertEqual(result["superseded"], 1)
        self.assertNotIn(old, {r["id"] for r in self.refs()})

    def test_queue_and_cursor_rollback_together(self):
        self.turn()
        self.turn(index=1)
        original = history.reference
        calls = 0
        def fail_second(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("Fixture failure")
            return original(*args)
        with mock.patch.object(history, "reference", side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, "Fixture failure"):
                history.collect(self.store)
        self.assertEqual(self.refs(), [])
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM history_cursors").fetchone()[0], 0)
        self.assertEqual(self.store.status()["recent_runs"][0]["state"], "failed")
        self.assertEqual(history.collect(self.store)["queued"], 2)

    def test_render_failure_recovers_without_duplicate_inputs(self):
        self.turn()
        with mock.patch.object(self.store, "render", side_effect=OSError("Fixture disk failure")):
            with self.assertRaises(OSError):
                history.collect(self.store)
        self.assertEqual(len(self.refs()), 1)
        self.assertEqual(history.collect(self.store)["queued"], 0)
        self.assertIn(self.refs()[0]["id"],
                      (self.store.local / "HISTORY_QUEUE.md").read_text(encoding="utf-8"))

    def test_schema_failure_is_visible_and_does_not_advance(self):
        with sqlite3.connect(self.source) as db:
            db.execute("ALTER TABLE turns RENAME COLUMN user_message TO changed")
        with self.assertRaisesRegex(ValueError, "Unsupported Copilot"):
            history.collect(self.store)
        self.assertEqual(self.store.status()["recent_runs"][0]["state"], "failed")
        self.assertEqual(self.refs(), [])

    def test_missing_source_is_not_created(self):
        config = history.load_config(self.store)
        missing = self.root / "missing.db"
        config["database"] = str(missing)
        memory.atomic_write(self.store.local / "history.json", json.dumps(config))
        with self.assertRaises(sqlite3.OperationalError):
            history.collect(self.store)
        self.assertFalse(missing.exists())

    def test_empty_user_turns_do_not_promote_assistant_claims(self):
        self.turn(message="")
        result = history.collect(self.store)
        self.assertEqual(result["empty_user_turns"], 1)
        self.assertEqual(self.refs(), [])

    def test_confirmed_distillation_is_atomic_and_idempotent(self):
        self.turn()
        history.collect(self.store)
        key = self.refs()[0]["id"]
        with self.assertRaises(ValueError):
            history.resolve(self.store, key, "distilled", observation())
        first = history.resolve(self.store, key, "distilled", observation(), confirmed=True)
        second = history.resolve(self.store, key, "distilled", observation(), confirmed=True)
        self.assertEqual(first["candidate_ids"], second["candidate_ids"])
        self.assertTrue(second["already_resolved"])
        self.assertEqual(len(self.store.rows("pending")), 1)
        self.assertEqual(self.store.rows("pending")[0]["source"], "copilot-session:session-a")
        self.assertEqual(self.refs(), [])
        self.assertEqual(history.collect(self.store)["queued"], 0)
        with self.assertRaisesRegex(ValueError, "resolved differently"):
            history.resolve(self.store, key, "distilled", observation("Different rule."), confirmed=True)

    def test_invalid_observation_rolls_back_entire_resolution(self):
        self.turn()
        history.collect(self.store)
        key = self.refs()[0]["id"]
        payload = observation()
        payload["observations"].append(dict(payload["observations"][0], non_sensitive=False))
        with self.assertRaises(ValueError):
            history.resolve(self.store, key, "distilled", payload, confirmed=True)
        self.assertEqual(len(self.refs()), 1)
        self.assertEqual(self.store.rows("pending"), [])

    def test_changed_source_requires_new_interactive_review(self):
        self.turn()
        history.collect(self.store)
        key = self.refs()[0]["id"]
        with sqlite3.connect(self.source) as db:
            db.execute("UPDATE turns SET user_message='Revised instruction'")
        with self.assertRaisesRegex(ValueError, "missing, changed or outside scope"):
            history.resolve(self.store, key, "distilled", observation(), confirmed=True)
        self.assertEqual(self.store.rows("pending"), [])
        self.assertEqual(len(self.refs()), 1)

    def test_scope_narrowing_blocks_old_reference_distillation(self):
        self.turn()
        history.collect(self.store)
        key = self.refs()[0]["id"]
        history.configure(self.store, self.source, ["different/repo"], 30,
                          confirmed=True, replace=True)
        with self.assertRaisesRegex(ValueError, "outside scope"):
            history.resolve(self.store, key, "distilled", observation(), confirmed=True)
        self.assertEqual(self.store.rows("pending"), [])

    def test_dismissal_does_not_need_source_or_copy_explanation(self):
        self.turn()
        history.collect(self.store)
        key = self.refs()[0]["id"]
        self.source.unlink()
        history.resolve(self.store, key, "dismissed", reason="sensitive", confirmed=True)
        repeated = history.resolve(self.store, key, "dismissed", reason="sensitive", confirmed=True)
        self.assertTrue(repeated["already_resolved"])
        self.assertEqual(self.store.rows("pending"), [])

    def test_missing_disabled_and_malformed_configuration(self):
        config_path = self.store.local / "history.json"
        config = history.load_config(self.store)
        config["enabled"] = False
        memory.atomic_write(config_path, json.dumps(config))
        self.assertEqual(history.collect(self.store)["state"], "skipped")
        config_path.unlink()
        self.assertEqual(history.collect(self.store)["state"], "skipped")
        memory.atomic_write(config_path, "{}")
        with self.assertRaises(ValueError):
            history.collect(self.store)
        self.assertEqual(self.store.status()["recent_runs"][0]["state"], "failed")

    def test_history_lock_and_configuration_confirmation(self):
        with memory.worker_lock(self.store.local):
            with self.assertRaisesRegex(RuntimeError, "Another memory worker"):
                history.collect(self.store)
        with self.assertRaises(ValueError):
            history.configure(self.store, self.source, ["*"], 30)
        with self.assertRaisesRegex(ValueError, "already configured"):
            history.configure(self.store, self.source, ["*"], 30, confirmed=True)

    def test_same_session_does_not_become_multiple_independent_sources(self):
        self.turn()
        self.turn(index=1)
        history.collect(self.store)
        for index, ref in enumerate(self.refs()):
            history.resolve(self.store, ref["id"], "distilled",
                            observation(f"Verified method {index}."), confirmed=True)
        self.assertEqual(len({r["source"] for r in self.store.rows("pending")}), 1)


if __name__ == "__main__":
    unittest.main()
