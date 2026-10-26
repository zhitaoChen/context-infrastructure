from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from tools.brain import agent_history, history, memory, observer


def stamp():
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


class AgentHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "AGENTS.md").write_text("Fixture", encoding="utf-8")
        self.claude = self.root / "claude"
        self.codex = self.root / "codex"
        self.claude.mkdir()
        self.codex.mkdir()
        self.store = memory.Store(self.root)
        config = {
            "version": 1,
            "enabled": True,
            "sources": {
                "claude": [str(self.claude.resolve())],
                "codex": [str(self.codex.resolve())],
            },
            "since": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
        }
        memory.atomic_write(self.store.local / "agent_history.json",
                            json.dumps(config))

    def tearDown(self):
        self.temp.cleanup()

    def write_claude(self, text="Always verify reusable workflow outputs."):
        events = [
            {"type": "user", "sessionId": "claude-session", "cwd": "fixture",
             "timestamp": stamp(), "message": {"content": text}},
            {"type": "assistant", "sessionId": "claude-session", "timestamp": stamp(),
             "message": {"content": "UNVERIFIED_ASSISTANT_SENTINEL"}},
        ]
        (self.claude / "session.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
        )

    def write_codex(self, text="Never claim success without validation."):
        events = [
            {"type": "session_meta", "timestamp": stamp(),
             "payload": {"id": "codex-session", "cwd": "fixture"}},
            {"type": "event_msg", "timestamp": stamp(),
             "payload": {"type": "user_message", "message": text}},
            {"type": "event_msg", "timestamp": stamp(),
             "payload": {"type": "agent_message", "message": "ASSISTANT_SENTINEL"}},
        ]
        (self.codex / "rollout-2026-01-01T00-00-00-codex-session.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
        )

    def test_collects_references_without_persisting_conversations(self):
        self.write_claude("CLAUDE_PRIVATE_SENTINEL workflow")
        self.write_codex("CODEX_PRIVATE_SENTINEL workflow")
        result = agent_history.collect(self.store)
        self.assertEqual(result["queued"], 2)
        self.assertEqual(result["sources"], {"claude": 1, "codex": 1})
        self.assertEqual(agent_history.collect(self.store)["queued"], 0)
        for path in self.store.local.rglob("*"):
            if path.is_file():
                content = path.read_bytes()
                self.assertNotIn(b"CLAUDE_PRIVATE_SENTINEL", content)
                self.assertNotIn(b"CODEX_PRIVATE_SENTINEL", content)
                self.assertNotIn(b"ASSISTANT_SENTINEL", content)

    def test_observer_holds_local_sources_for_interactive_review(self):
        self.write_claude()
        self.write_codex()
        agent_history.collect(self.store)
        observer.configure(self.store, confirmed=True)

        def model(*args):
            self.fail("Local agent history reached the unattended model")

        result = observer.run(self.store, model)
        self.assertEqual(result["model_inputs"], 0)
        self.assertEqual(result["held_for_review"], 2)
        self.assertEqual(len(history.list_pending(
            self.store, state="needs_review"
        )), 2)

    def test_generated_claude_user_events_are_not_collected(self):
        self.write_claude("<local-command-stdout>workflow output</local-command-stdout>")
        self.assertEqual(agent_history.collect(self.store)["queued"], 0)
        self.assertEqual(history.list_pending(self.store), [])

    def test_changed_turn_is_superseded_and_must_be_recollected(self):
        self.write_claude()
        agent_history.collect(self.store)
        with self.store.connection() as db:
            ref = dict(db.execute(
                "SELECT * FROM history_queue WHERE state='pending'"
            ).fetchone())
        self.write_claude("Always verify revised reusable outputs.")
        with self.assertRaisesRegex(ValueError, "changed"):
            history.verify_current_source(self.store, ref)
        result = agent_history.collect(self.store)
        self.assertEqual(result["superseded"], 1)
        self.assertEqual(result["queued"], 1)

    def test_pi_and_gemini_are_reference_only_and_held_for_review(self):
        pi = self.root / "pi"
        gemini = self.root / "gemini/chats"
        pi.mkdir()
        gemini.mkdir(parents=True)
        events = [
            {"type": "session", "id": "pi-session", "version": 3, "cwd": "private"},
            {"type": "message", "timestamp": stamp(), "message": {
                "role": "system", "content": "SYSTEM_SENTINEL"}},
            {"type": "message", "id": "user-node", "timestamp": stamp(), "message": {
                "role": "user", "content": [{"type": "text", "text": "PI_PRIVATE_SENTINEL"},
                                             {"type": "image", "data": "IMAGE_SENTINEL"}]}},
            {"type": "message", "timestamp": stamp(), "message": {
                "role": "toolResult", "content": "TOOL_SENTINEL"}},
        ]
        file = pi / "session.jsonl"
        file.write_text("".join(json.dumps(e) + "\n" for e in events) + '{', encoding="utf-8")
        (gemini / "session-fixture.json").write_text(json.dumps({
            "sessionId": "gemini-session", "messages": [
                {"type": "user", "timestamp": stamp(), "content": "GEMINI_PRIVATE_SENTINEL"},
                {"type": "gemini", "timestamp": stamp(), "content": "ASSISTANT_SENTINEL"},
            ]}), encoding="utf-8")
        config = agent_history.load_config(self.store)
        config["sources"] = {"pi": [str(pi)], "gemini": [str(gemini.parent)]}
        memory.atomic_write(self.store.local / "agent_history.json", json.dumps(config))
        self.assertEqual(agent_history.collect(self.store)["sources"], {"gemini": 1, "pi": 1})
        self.assertEqual(agent_history.collect(self.store)["queued"], 0)
        observer.configure(self.store, confirmed=True)
        result = observer.run(self.store, lambda *args: self.fail("Protected source sent to model"))
        self.assertEqual(result["held_for_review"], 2)
        with self.store.connection() as db:
            refs = [dict(row) for row in db.execute("SELECT * FROM history_queue")]
        for ref in refs:
            self.assertIsNotNone(history.get_turn(self.store, ref))
        for path in self.store.local.rglob("*"):
            if path.is_file():
                self.assertNotIn(b"PRIVATE_SENTINEL", path.read_bytes())
                self.assertNotIn(b"TOOL_SENTINEL", path.read_bytes())
        events[0]["parentSession"] = "original.jsonl"
        file.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
        # Upstream retains branch nodes and deduplicates by stable node ID.
        self.assertEqual(len(list(agent_history.pi_rows([str(pi)]))), 1)

    def test_gemini_snapshots_use_latest_version_without_requeue_churn(self):
        chats = self.root / "snapshots/chats"
        chats.mkdir(parents=True)
        old = {"sessionId": "shared-session", "lastUpdated": "2026-01-01T00:00:00Z",
               "messages": [{"type": "user", "timestamp": stamp(), "content": "Old request"}]}
        new = dict(old, lastUpdated="2026-02-01T00:00:00Z", messages=[
            {"type": "user", "timestamp": stamp(), "content": "Updated request"}])
        (chats / "session-old.json").write_text(json.dumps(old), encoding="utf-8")
        (chats / "session-new.json").write_text(json.dumps(new), encoding="utf-8")
        config = agent_history.load_config(self.store)
        config["sources"] = {"gemini": [str(chats.parent)]}
        memory.atomic_write(self.store.local / "agent_history.json", json.dumps(config))
        rows = agent_history.scan_rows(config)
        self.assertEqual([row["user_message"] for row in rows], ["Updated request"])
        self.assertEqual(agent_history.collect(self.store)["queued"], 1)
        self.assertEqual(agent_history.collect(self.store)["queued"], 0)
        self.assertEqual(agent_history.collect(self.store)["superseded"], 0)

    def test_missing_approved_root_fails_explicitly(self):
        self.claude.rmdir()
        with self.assertRaisesRegex(ValueError, "unavailable"):
            agent_history.collect(self.store)

    def test_confirmation_and_missing_sources_are_rejected(self):
        with self.assertRaises(ValueError):
            agent_history.configure(self.store, ["claude"], 30, replace=True)
        with self.assertRaises(ValueError):
            agent_history.configure(self.store, ["unknown"], 30,
                                    confirmed=True, replace=True)


if __name__ == "__main__":
    unittest.main()
