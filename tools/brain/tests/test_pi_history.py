from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools.brain import agent_history, history, memory, observer


def stamp(days=1):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def user(key="user-a", parent="system", content=None, time=None):
    return {"type": "message", "id": key, "parentId": parent, "timestamp": time or stamp(),
            "message": {"role": "user", "content": content if content is not None else [
                {"type": "text", "text": "Always verify the workflow. PI_PRIVATE_SENTINEL"},
            ]}}


class PiHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "AGENTS.md").write_text("Fixture", encoding="utf-8")
        self.sessions = self.root / "pi-sessions"
        self.sessions.mkdir()
        self.store = memory.Store(self.root)
        agent_history.configure(self.store, ["pi"], 30, confirmed=True, pi_root=self.sessions)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, events, filename="session.jsonl", version=3):
        header = {"type": "session", "version": version, "id": "pi-session",
                  "timestamp": stamp(), "cwd": "PRIVATE_PATH_SENTINEL"}
        path = self.sessions / filename
        path.write_text("".join(json.dumps(event) + "\n" for event in [header, *events]),
                        encoding="utf-8")
        return path

    def test_user_only_reference_capture_and_privacy(self):
        self.write([
            {"type": "message", "id": "system", "message": {"role": "system", "content": "SYSTEM_SECRET"}},
            user(content=[{"type": "text", "text": "PI_PRIVATE_SENTINEL workflow"},
                          {"type": "image", "data": "IMAGE_SECRET"}]),
            {"type": "message", "id": "assistant", "message": {
                "role": "assistant", "content": [{"type": "thinking", "thinking": "REASONING_SECRET"}]}},
            {"type": "message", "id": "tool", "message": {"role": "toolResult", "content": "TOOL_SECRET"}},
            {"type": "compaction", "summary": "SUMMARY_SECRET"},
        ])
        result = agent_history.collect(self.store)
        self.assertEqual(result["sources"], {"pi": 1})
        self.assertEqual(result["queued"], 1)
        self.assertEqual(agent_history.collect(self.store)["queued"], 0)
        for path in self.store.local.rglob("*"):
            if path.is_file():
                data = path.read_bytes()
                for sentinel in ("PI_PRIVATE_SENTINEL", "PRIVATE_PATH_SENTINEL", "SYSTEM_SECRET",
                                 "IMAGE_SECRET", "REASONING_SECRET", "TOOL_SECRET", "SUMMARY_SECRET"):
                    self.assertNotIn(sentinel.encode(), data)

    def test_branches_and_pruning_do_not_renumber(self):
        self.write([user("a"), user("b", "a"), user("c", "a")])
        rows = agent_history.scan_rows(agent_history.load_config(self.store))
        original = {row["content_digest"] + str(row["turn_index"]): row["turn_index"] for row in rows}
        self.assertEqual(len(set(original.values())), 3)
        indexes = [row["turn_index"] for row in rows]
        self.write([user("c", "a"), user("b", "a")])
        current = agent_history.scan_rows(agent_history.load_config(self.store))
        self.assertEqual({row["turn_index"] for row in current}, set(indexes) - {
            int(agent_history.digest(["pi-entry", "a"])[:15], 16)})
        self.assertTrue(all(0 <= row["turn_index"] < 2 ** 63 for row in current))

    def test_duplicate_export_deduplicates_but_conflict_is_rejected(self):
        event = user()
        self.write([event])
        self.write([event], filename="export.jsonl")
        self.assertEqual(agent_history.collect(self.store)["queued"], 1)
        self.write([dict(event, message={"role": "user", "content": "Conflicting text"})],
                   filename="export.jsonl")
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            agent_history.collect(self.store)
        self.assertEqual(self.store.status()["recent_runs"][0]["state"], "failed")

    def test_active_partial_tail_is_retried_and_complete_corruption_fails(self):
        path = self.write([user()])
        with path.open("a", encoding="utf-8") as stream:
            stream.write('{"type": "message"')
        self.assertEqual(agent_history.collect(self.store)["queued"], 1)
        self.write([user(), user("b")])
        self.assertEqual(agent_history.collect(self.store)["queued"], 1)
        with path.open("a", encoding="utf-8") as stream:
            stream.write("invalid complete line\n")
        with self.assertRaisesRegex(ValueError, "Malformed completed"):
            agent_history.collect(self.store)

    def test_unknown_version_or_invalid_user_id_fails_without_consuming(self):
        for version, events in ((4, [user()]), (3, [user(key="../invalid")])):
            self.write(events, version=version)
            with self.assertRaises(ValueError):
                agent_history.collect(self.store)
            self.assertEqual(history.list_pending(self.store), [])

    def test_backfill_cutoff_and_bounded_queue(self):
        self.write([user("old", time=stamp(40)), user("recent"), user("other")])
        first = agent_history.collect(self.store, maximum=1)
        self.assertTrue(first["more"])
        self.assertEqual(first["queued"], 1)
        self.assertEqual(agent_history.collect(self.store, maximum=1)["queued"], 1)
        self.assertEqual(agent_history.collect(self.store)["queued"], 0)
        self.assertEqual(len(history.list_pending(self.store)), 2)

    def test_observer_never_sends_pi_raw_text_unattended(self):
        self.write([user()])
        agent_history.collect(self.store)
        observer.configure(self.store, confirmed=True)
        def forbidden(*args):
            self.fail("Pi text reached the cloud model")
        result = observer.run(self.store, forbidden)
        self.assertEqual(result["held_for_review"], 1)
        ref = history.list_pending(self.store, state="needs_review")[0]
        with self.store.connection() as db:
            ref = dict(db.execute("SELECT * FROM history_queue WHERE id=?", (ref["id"],)).fetchone())
        self.assertEqual(history.reference_source(self.store, ref), "pi-session:pi-session")
        result = history.resolve(self.store, ref["id"], "distilled", {"observations": [{
            "observation": "Verify workflow outputs before claiming completion.",
            "evidence": "The user explicitly asked for a reusable verification requirement.",
            "non_sensitive": True, "durable": True,
        }]}, confirmed=True)
        self.assertEqual(result["state"], "distilled")
        self.assertEqual(self.store.rows("pending")[0]["source"], "pi-session:pi-session")

    def test_source_updates_supersede_old_reference(self):
        event = user()
        self.write([event])
        agent_history.collect(self.store)
        ref = history.list_pending(self.store)[0]
        with self.store.connection() as db:
            ref = dict(db.execute("SELECT * FROM history_queue WHERE id=?", (ref["id"],)).fetchone())
        self.write([dict(event, message={"role": "user", "content": "Revised workflow request"})])
        with self.assertRaisesRegex(ValueError, "changed"):
            history.verify_current_source(self.store, ref)
        result = agent_history.collect(self.store)
        self.assertEqual(result["queued"], 1)
        self.assertEqual(result["superseded"], 1)

    def test_recognized_child_export_is_excluded_with_notice(self):
        self.write([user()])
        export = {"version": 1, "recordType": "message", "source": "async",
                  "sourceEventType": "initial_prompt", "role": "user", "runId": "run-fixture",
                  "agent": "scout", "childIndex": 0,
                  "message": {"role": "user", "content": "CHILD_NOT_USER_EVIDENCE"}}
        (self.sessions / "fixture_scout_transcript.jsonl").write_text(
            json.dumps(export) + "\n", encoding="utf-8")
        for include in (False, True):
            with self.assertWarnsRegex(RuntimeWarning, "recognized pi-subagents"):
                rows = list(agent_history.pi_rows([str(self.sessions)], include_assistant=include))
            self.assertEqual(len(rows), 1)
            self.assertNotIn("CHILD_NOT_USER_EVIDENCE", str(rows))

    def test_unknown_export_and_native_version_are_not_silently_skipped(self):
        for event in ({"version": 1, "recordType": "message"},
                      {"type": "session", "version": 4, "id": "future", "cwd": "fixture"}):
            path = self.sessions / "unknown_transcript.jsonl"
            path.write_text(json.dumps(event) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unsupported pi session"):
                list(agent_history.pi_rows([str(self.sessions)]))
            path.unlink()

    def test_custom_pi_roots_respect_environment_and_config(self):
        with mock.patch.dict(os.environ, {"PI_CODING_AGENT_DIR": str(self.root / "agent"),
                                         "PI_CODING_AGENT_SESSION_DIR": str(self.sessions)}):
            self.assertEqual(agent_history.default_roots("pi"), [self.sessions])
        with mock.patch.dict(os.environ, {"PI_CODING_AGENT_DIR": str(self.root / "agent"),
                                         "PI_CODING_AGENT_SESSION_DIR": ""}):
            self.assertEqual(agent_history.default_roots("pi"), [self.root / "agent" / "sessions"])
        with self.assertRaises(ValueError):
            agent_history.configure(self.store, ["pi"], 30, pi_root=self.sessions)
        with self.assertRaisesRegex(ValueError, "--pi-root requires"):
            agent_history.configure(self.store, ["claude"], 30, confirmed=True, replace=True,
                                    pi_root=self.sessions)

    def test_source_binding_must_refresh_and_injected_user_messages_are_filtered(self):
        self.write([user(content="<system-reminder>generated content</system-reminder>"),
                    user("image-only", content=[{"type": "image", "data": "private"}])])
        self.assertEqual(agent_history.collect(self.store)["queued"], 0)
        observer.configure(self.store, confirmed=True)
        config = json.loads((self.store.local / "observer.json").read_text(encoding="utf-8"))
        config["history_origins"] = ["unrelated"]
        memory.atomic_write(self.store.local / "observer.json", json.dumps(config))
        with self.assertRaisesRegex(ValueError, "source changed"):
            observer.run(self.store)


if __name__ == "__main__":
    unittest.main()
