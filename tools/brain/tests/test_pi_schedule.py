import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import memory
import pi_runtime
import pi_schedule


class PiTests(unittest.TestCase):
    def events(self, content='{"ready":true}', reason="stop", aborted=False):
        return "\n".join(json.dumps(event) for event in [
            {"type": "message_end", "message": {"role": "assistant", "stopReason": reason,
                "content": [{"type": "text", "text": content}]}},
            {"type": "agent_settled", "aborted": aborted}])

    def test_parse(self):
        self.assertEqual(pi_runtime.parse_output(self.events()), {"ready": True})
        for reason in ("error", "aborted", "length", "toolUse"):
            with self.assertRaises(RuntimeError):
                pi_runtime.parse_output(self.events(reason=reason))
        with self.assertRaises(RuntimeError):
            pi_runtime.parse_output(self.events(aborted=True))
        with self.assertRaises(ValueError):
            pi_runtime.parse_output('{"type":"tool_execution_start"}\n' + self.events())
        with self.assertRaises(RuntimeError):
            pi_runtime.parse_output(self.events().split("\n")[0])

    def test_lf_framing(self):
        self.assertEqual(pi_runtime.parse_output(self.events('{"value":"a\u2028b"}')),
                         {"value": "a\u2028b"})

    def test_paths(self):
        for path in ("rules/USER.local.md", "contexts/memory/.local/memory.db", ".env",
                     "tools/archive/file.py", "rules/../other.md", "docs/.hidden/file.md",
                     "docs/auth.json", ".pi-loop.json.lock"):
            self.assertFalse(pi_schedule.allowed_path(path), path)
        for path in ("rules/skills/example.md", "tools/brain/pi_schedule.py", "docs/CRONTAB.md"):
            self.assertTrue(pi_schedule.allowed_path(path), path)

    def test_review_fail_closed(self):
        rows = [{"path": "docs/example.md"}]
        for payload in ({"decisions": []}, {"decisions": [{"path": "elsewhere", "safe": True}]},
                        {"decisions": [{"path": "docs/example.md", "safe": False}]},
                        {"decisions": [{"path": "docs/example.md", "safe": "true"}]}):
            with self.assertRaises((ValueError, RuntimeError)):
                pi_schedule.review_publication(None, rows, lambda *args: payload)

    def test_restricted_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text("test")
            store = memory.Store(root)
            prompts = root / "periodic_jobs/ai_heartbeat/prompts"
            prompts.mkdir(parents=True)
            (prompts / "daily_observer.md").write_text("test")
            config = {"pi_command": ["pi"], "provider": "test", "model": "test",
                      "agent_dir": tmp, "timeout_seconds": 60}
            (store.local / "pi_runtime.json").write_text(json.dumps(config))
            process = mock.Mock(returncode=0)
            process.communicate.return_value = (self.events(), "")
            with mock.patch.object(pi_runtime.subprocess, "Popen", return_value=process) as popen:
                pi_runtime.call_pi(store, "daily", [])
                for flag in ("--no-tools", "--no-extensions", "--no-mcp", "--no-context-files",
                             "--no-session", "--no-approve"):
                    self.assertIn(flag, popen.call_args.args[0])
            process.communicate.side_effect = subprocess.TimeoutExpired("pi", 60)
            with mock.patch.object(pi_runtime.subprocess, "Popen", return_value=process), \
                    mock.patch.object(memory, "stop_process_tree") as stop:
                with self.assertRaises(RuntimeError):
                    pi_runtime.call_pi(store, "daily", [])
                stop.assert_called_once_with(process)


class GitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.remote = self.base / "remote.git"
        self.root = self.base / "work"
        subprocess.run(["git", "init", "--bare", str(self.remote)], check=True, capture_output=True)
        subprocess.run(["git", "init", "-b", "main", str(self.root)], check=True, capture_output=True)
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        self.git("config", "core.autocrlf", "false")
        (self.root / "AGENTS.md").write_text("public rules\n")
        (self.root / ".gitignore").write_text("contexts/memory/.local/\n")
        self.git("add", "AGENTS.md", ".gitignore")
        self.git("commit", "-m", "initial")
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "origin", "main")
        self.store = memory.Store(self.root)
        self.config = {"branch": "main", "remote": str(self.remote)}

    def git(self, *args):
        return pi_schedule.git(self.root, *args)

    def approve(self, store, kind, rows):
        return {"decisions": [{"path": row["path"], "safe": True} for row in rows]}

    def test_push_and_skip(self):
        (self.root / "AGENTS.md").write_text("updated public rules\n")
        preview = pi_schedule.sync_public(self.store, self.config, True, self.approve)
        self.assertEqual(preview["state"], "preview")
        result = pi_schedule.sync_public(self.store, self.config, model=self.approve)
        self.assertEqual(result["state"], "pushed")
        self.assertEqual(self.git("rev-parse", "HEAD").strip(),
                         self.git("ls-remote", "origin", "refs/heads/main").split()[0])
        self.assertEqual(pi_schedule.sync_public(self.store, self.config)["state"], "skipped")

    def test_deleted_tracked_file(self):
        (self.root / "AGENTS.md").unlink()
        result = pi_schedule.sync_public(self.store, self.config, model=self.approve)
        self.assertEqual(result["state"], "pushed")
        self.assertEqual(self.git("ls-tree", "HEAD", "--", "AGENTS.md"), b"")

    def test_crlf_normalization(self):
        self.git("config", "core.autocrlf", "true")
        (self.root / "AGENTS.md").write_bytes(b"updated rules\r\n")
        self.assertEqual(pi_schedule.sync_public(self.store, self.config, model=self.approve)["state"],
                         "pushed")

    def test_unvalidated_retry_is_blocked(self):
        previous = self.git("rev-parse", "HEAD").decode().strip()
        (self.root / "AGENTS.md").write_text("unreviewed")
        self.git("commit", "-am", "unreviewed")
        current = self.git("rev-parse", "HEAD").decode().strip()
        (self.store.local / "pi_publication.json").write_text(json.dumps(
            {"pending_commit": current, "base": previous}))
        with self.assertRaisesRegex(RuntimeError, "history differs"):
            pi_schedule.sync_public(self.store, self.config)

    def test_remote_change_is_blocked(self):
        self.config["remote"] = "https://example.invalid/changed"
        with self.assertRaisesRegex(RuntimeError, "remote changed"):
            pi_schedule.sync_public(self.store, self.config)

    def test_untracked_and_staged(self):
        (self.root / "private.md").write_text("do not publish")
        self.assertEqual(pi_schedule.sync_public(self.store, self.config)["state"], "skipped")
        self.git("add", "private.md")
        with self.assertRaisesRegex(RuntimeError, "staged"):
            pi_schedule.sync_public(self.store, self.config)

    def test_unreviewed_commit_blocked(self):
        (self.root / "AGENTS.md").write_text("changed")
        self.git("commit", "-am", "user change")
        with self.assertRaisesRegex(RuntimeError, "history differs"):
            pi_schedule.sync_public(self.store, self.config)

    def test_changed_during_review(self):
        (self.root / "AGENTS.md").write_text("review me")
        def race(store, kind, rows):
            (self.root / "AGENTS.md").write_text("changed after review")
            return self.approve(store, kind, rows)
        with self.assertRaisesRegex(RuntimeError, "reviewed file changed"):
            pi_schedule.sync_public(self.store, self.config, model=race)

    def test_failed_push_retry_only_validated_commit(self):
        (self.root / "AGENTS.md").write_text("public rules updated")
        original = pi_schedule.git
        def fail_push(root, *args, **kwargs):
            if args[0] == "push":
                raise RuntimeError("network unavailable")
            return original(root, *args, **kwargs)
        with mock.patch.object(pi_schedule, "git", side_effect=fail_push):
            with self.assertRaises(RuntimeError):
                pi_schedule.sync_public(self.store, self.config, model=self.approve)
        result = pi_schedule.sync_public(self.store, self.config, model=self.approve)
        self.assertEqual(result["state"], "pushed")


if __name__ == "__main__":
    unittest.main()
