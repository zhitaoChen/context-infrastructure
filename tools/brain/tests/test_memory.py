import concurrent.futures
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location("brain_memory", Path(__file__).parents[1] / "memory.py")
memory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(memory)


def record(source="test-a", observation="Validate structured outputs before applying changes."):
    return {"source": source, "observation": observation,
            "evidence": "A malformed fixture was rejected without changing stored records.",
            "non_sensitive": True, "durable": True}


def keep_model(store, kind, rows):
    return {"decisions": [{"id": r["id"], "decision": "keep", "reason": "Verified method"}
                          for r in rows]}


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "AGENTS.md").write_text("Test-only brain", encoding="utf-8")
        self.store = memory.Store(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_capture_idempotent_and_original_evidence_preserved(self):
        first = self.store.capture(record())
        second = self.store.capture(record())
        self.assertTrue(first["inserted"])
        self.assertFalse(second["inserted"])
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.store.rows("pending")), 1)

    def test_capture_requires_attestations(self):
        for field in ("non_sensitive", "durable"):
            value = record()
            value[field] = False
            with self.assertRaises(ValueError):
                self.store.capture(value)
        self.assertEqual(self.store.rows("pending"), [])

    def test_reject_credentials_control_chars_and_extra_fields(self):
        for observation in ("password=not-for-memory", "two\nlines", "ghp_" + "a" * 30):
            with self.assertRaises(ValueError):
                self.store.capture(record(observation=observation))
        value = record()
        value["extra"] = "unexpected"
        with self.assertRaises(ValueError):
            self.store.capture(value)

    def test_concurrent_capture_has_no_lost_entries(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            list(executor.map(lambda i: self.store.capture(record(source=f"fixture-{i}")), range(24)))
        rows = self.store.rows("pending")
        self.assertEqual(len(rows), 24)
        view = (self.store.local / "INBOX.md").read_text(encoding="utf-8")
        self.assertTrue(all(row["id"] in view for row in rows))

    def test_empty_worker_does_not_call_model(self):
        def unexpected(*args):
            self.fail("Empty input called a model")
        self.assertEqual(memory.run_worker(self.store, "daily", unexpected)["state"], "skipped")
        self.assertEqual(memory.run_worker(self.store, "weekly", unexpected)["state"], "skipped")

    def test_new_capture_during_model_call_stays_pending(self):
        self.store.capture(record())
        def capturing_model(store, kind, rows):
            store.capture(record(source="added-during-processing"))
            return keep_model(store, kind, rows)
        memory.run_worker(self.store, "daily", capturing_model)
        self.assertEqual(len(self.store.rows("accepted")), 1)
        self.assertEqual(len(self.store.rows("pending")), 1)

    def test_malformed_batch_changes_nothing_and_records_failure(self):
        self.store.capture(record())
        self.store.capture(record(source="test-b"))
        def partial(store, kind, rows):
            return keep_model(store, kind, rows[:1])
        with self.assertRaises(ValueError):
            memory.run_worker(self.store, "daily", partial)
        self.assertEqual(len(self.store.rows("pending")), 2)
        self.assertEqual(self.store.rows("accepted"), [])
        self.assertEqual(self.store.status()["recent_runs"][0]["state"], "failed")
        memory.run_worker(self.store, "daily", keep_model)
        self.assertEqual(len(self.store.rows("accepted")), 2)

    def test_daily_retries_one_invalid_model_response(self):
        self.store.capture(record())
        calls = 0

        def flaky(store, kind, rows):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"decisions": [{"id": "unknown", "decision": "keep",
                                       "reason": "Invalid first attempt"}]}
            return keep_model(store, kind, rows)

        result = memory.run_worker(self.store, "daily", flaky)
        self.assertEqual(result["model_attempts"], 2)
        self.assertEqual(len(self.store.rows("accepted")), 1)

    def test_duplicate_unknown_and_invalid_decisions(self):
        self.store.capture(record())
        rows = self.store.rows("pending")
        valid = keep_model(self.store, "daily", rows)["decisions"][0]
        for items in ([valid, valid], [dict(valid, id="unknown")], [dict(valid, decision="maybe")]):
            with self.assertRaises(ValueError):
                memory.daily_decisions({"decisions": items}, rows)

    def test_daily_bounded_batch_does_not_drop_backlog(self):
        for i in range(memory.MAX_BATCH + 1):
            self.store.capture(record(source=f"source-{i}"))
        memory.run_worker(self.store, "daily", keep_model)
        self.assertEqual(len(self.store.rows("pending")), 1)

    def test_weekly_requires_independent_sources(self):
        self.store.capture(record())
        self.store.capture(record(observation="Use atomic replacement for generated files."))
        memory.run_worker(self.store, "daily", keep_model)
        self.assertEqual(memory.run_worker(self.store, "weekly")["state"], "skipped")
        rows = self.store.rows("accepted")
        with self.assertRaises(ValueError):
            memory.weekly_proposals({"proposals": [{
                "title": "Draft", "category": "skill", "proposal": "Validate outputs.",
                "ids": [r["id"] for r in rows],
            }]}, rows)

    def test_weekly_is_review_only_and_idempotent(self):
        self.store.capture(record())
        self.store.capture(record(source="independent-test-b"))
        memory.run_worker(self.store, "daily", keep_model)
        before = (self.root / "AGENTS.md").read_bytes()
        def propose(store, kind, rows):
            return {"proposals": [{
                "title": "Output validation", "category": "skill",
                "proposal": "Validate output schemas before applying changes.",
                "ids": [r["id"] for r in rows],
            }]}
        result = memory.run_worker(self.store, "weekly", propose)
        self.assertTrue(Path(result["review"]).exists())
        self.assertEqual((self.root / "AGENTS.md").read_bytes(), before)
        self.assertEqual(memory.run_worker(self.store, "weekly", propose)["state"], "skipped")
        self.assertEqual(self.store.status()["review_batches"], 1)
        self.assertEqual(len(self.store.rows("accepted")), 2)
        review_id = Path(result["review"]).stem
        self.assertEqual(self.store.status()["pending_reviews"], [review_id])
        with self.assertRaises(ValueError):
            self.store.resolve_review(review_id, "applied", "Not authorized", False)
        self.store.resolve_review(review_id, "dismissed", "User decided the existing rule suffices.", True)
        self.assertEqual(self.store.status()["pending_reviews"], [])
        self.assertIn("Status: dismissed", Path(result["review"]).read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            self.store.resolve_review(review_id, "applied", "Conflicting decision", True)

    def test_worker_lock_is_exclusive(self):
        with memory.worker_lock(self.store.local):
            with self.assertRaises(RuntimeError):
                with memory.worker_lock(self.store.local):
                    self.fail("Second worker acquired the lock")

    def test_weekly_drains_large_backlog_in_bounded_windows(self):
        with self.store.connection() as db:
            for index in range(140):
                key, fields = memory.prepare_record(record(
                    source=f"source-{index % 2}", observation=f"Verified reusable method {index}."))
                db.execute("INSERT INTO candidates(id,created,source,observation,evidence,state,reason)"
                           " VALUES (?,?,?,?,?,'accepted','fixture')",
                           (key, memory.now(), fields["source"], fields["observation"], fields["evidence"]))
        sizes = []
        def review(store, kind, rows):
            sizes.append(len(rows))
            return {"proposals": []}
        first = memory.run_worker(self.store, "weekly", review)
        self.assertEqual(first["remaining_unreviewed"], 12)
        second = memory.run_worker(self.store, "weekly", review)
        self.assertEqual(second["remaining_unreviewed"], 0)
        self.assertEqual(self.store.status()["unreviewed_observations"], 0)
        self.assertTrue(all(size <= 128 for size in sizes))
        self.assertEqual(memory.run_worker(self.store, "weekly", review)["state"], "skipped")
        self.assertEqual(len(sizes), 2)

    def test_legacy_review_snapshot_backfills_coverage_without_model(self):
        self.store.capture(record())
        self.store.capture(record(source="second-source"))
        memory.run_worker(self.store, "daily", keep_model)
        memory.run_worker(self.store, "weekly", lambda *args: {"proposals": []})
        with self.store.connection() as db:
            db.execute("DELETE FROM review_inputs")
        def unexpected(*args):
            self.fail("Exact legacy snapshot must not be regenerated")
        self.assertEqual(memory.run_worker(self.store, "weekly", unexpected)["state"], "skipped")
        self.assertEqual(self.store.status()["unreviewed_observations"], 0)

    def test_weekly_supports_full_markdown_without_relaxing_capture(self):
        self.store.capture(record())
        self.store.capture(record(source="independent-source"))
        rows = self.store.rows("pending")
        body = "### Goal\n" + "A bounded method with explicit evidence and acceptance criteria. " * 30
        proposal = {"title": "Draft", "category": "skill", "proposal": body,
                    "ids": [row["id"] for row in rows]}
        self.assertGreater(len(body), 1200)
        self.assertEqual(memory.weekly_proposals({"proposals": [proposal]}, rows)["proposals"][0]["proposal"],
                         body)
        for invalid in ("bad\x00body", "x" * 6001):
            with self.assertRaises(ValueError):
                memory.weekly_proposals({"proposals": [dict(proposal, proposal=invalid)]}, rows)
        with self.assertRaises(ValueError):
            self.store.capture(record(observation=body))

    def test_views_can_be_rebuilt_and_interrupted_run_is_visible(self):
        self.store.capture(record())
        (self.store.local / "INBOX.md").write_text("broken", encoding="utf-8")
        with self.store.connection() as db:
            db.execute("INSERT INTO runs(id,kind,started,state) VALUES ('interrupted','daily',?,'running')",
                       (memory.now(),))
        memory.run_worker(self.store, "daily", keep_model)
        self.assertIn("Generated view", (self.store.local / "INBOX.md").read_text(encoding="utf-8"))
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT state FROM runs WHERE id='interrupted'").fetchone()[0],
                             "interrupted")

    def test_threshold_counts_only_content_and_excludes_archive(self):
        folder = self.root / "contexts" / "survey_sessions"
        folder.mkdir(parents=True)
        for i in range(100):
            (folder / f"report-{i}.md").write_text("Report", encoding="utf-8")
        (folder / "README.md").write_text("index", encoding="utf-8")
        (folder / "archive").mkdir()
        (folder / "archive" / "old.md").write_text("old", encoding="utf-8")
        status = memory.semantic_status(self.root)
        self.assertEqual(status["document_count"], 100)
        self.assertTrue(status["suggest_enable"])
        self.assertFalse(status["enabled"])

    def test_jsonl_requires_successful_result_and_no_tools(self):
        events = [
            {"type": "assistant.message", "data": {"content": '{"ready":true}', "toolRequests": []}},
            {"type": "result", "exitCode": 0},
        ]
        encode = lambda values: "\n".join(json.dumps(v) for v in values)
        self.assertEqual(memory.parse_copilot_output(encode(events)), {"ready": True})
        with self.assertRaises(ValueError):
            memory.parse_copilot_output(encode(events[:1]))
        with self.assertRaises(ValueError):
            memory.parse_copilot_output(encode([{"type": "tool.execution_start", "data": {}}] + events))
        with self.assertRaises(ValueError):
            memory.parse_copilot_output(encode([{
                "type": "session.usage_checkpoint", "data": {
                    "promptCacheBreakState": [{"models": {"test": {"tool_count": 1}}}]
                }
            }] + events))

    def test_timeout_stops_process_and_preserves_candidates(self):
        self.store.capture(record())
        config = {"gh": "gh", "gh_user": "fixture", "copilot_command": ["copilot"],
                  "timeout_seconds": 60}
        (self.store.local / "config.json").write_text(json.dumps(config), encoding="utf-8")
        prompts = self.root / "periodic_jobs" / "ai_heartbeat" / "prompts"
        prompts.mkdir(parents=True)
        (prompts / "daily_observer.md").write_text("Test prompt", encoding="utf-8")
        process = mock.Mock()
        process.communicate.side_effect = memory.subprocess.TimeoutExpired("copilot", 60)
        with mock.patch.object(memory.subprocess, "run",
                               return_value=mock.Mock(returncode=0, stdout="synthetic-auth-value")), \
                mock.patch.object(memory.subprocess, "Popen", return_value=process) as popen, \
                mock.patch.object(memory, "stop_process_tree") as stop:
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                memory.run_worker(self.store, "daily")
            stop.assert_called_once_with(process)
            command = popen.call_args.args[0]
            self.assertIn("--available-tools=__brain_no_tools__", command)
            self.assertNotIn("--no-auto-login", command)
            self.assertNotIn("--allow-all", command)
            self.assertNotIn("synthetic-auth-value", command)
        self.assertEqual(len(self.store.rows("pending")), 1)
        self.assertEqual(self.store.status()["recent_runs"][0]["state"], "failed")

    def test_missing_config_records_failure_without_consuming_inputs(self):
        self.store.capture(record())
        with self.assertRaisesRegex(ValueError, "Install the memory runtime"):
            memory.run_worker(self.store, "daily")
        self.assertEqual(len(self.store.rows("pending")), 1)
        self.assertEqual(self.store.status()["recent_runs"][0]["state"], "failed")


if __name__ == "__main__":
    unittest.main()
