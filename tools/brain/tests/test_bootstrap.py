import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.brain import bootstrap


class BootstrapTests(unittest.TestCase):
    def test_preserves_content_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            home = Path(directory)
            root = home / "brain"
            root.mkdir()
            (root / "AGENTS.md").write_text("fixture", encoding="utf-8")
            file = home / ".claude/CLAUDE.md"
            file.parent.mkdir()
            file.write_text("Existing instructions\n", encoding="utf-8")
            bootstrap.install(root, home)
            self.assertEqual(file.read_text(), "Existing instructions\n")
            result = bootstrap.install(root, home, True)
            self.assertEqual(len(result["entries"]), 5)
            self.assertTrue(file.read_text().startswith("Existing instructions\n"))
            self.assertTrue(file.with_name(file.name + ".personal-brain.bak").exists())
            self.assertFalse(any(e["changed"] for e in bootstrap.install(root, home, True)["entries"]))

    def test_rejects_broken_markers(self):
        for text in (bootstrap.START, bootstrap.END + bootstrap.START,
                     bootstrap.START + bootstrap.END + bootstrap.START + bootstrap.END):
            with self.assertRaises(ValueError):
                bootstrap.merge(text, "replacement")

    def test_override_and_environment_paths(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            home = Path(directory)
            codex = home / ".codex"
            codex.mkdir()
            (codex / "AGENTS.override.md").touch()
            self.assertEqual(bootstrap.targets(home)["codex"].name, "AGENTS.override.md")
            with patch.dict(os.environ, {"PI_CODING_AGENT_DIR": str(home / "custom")}):
                self.assertEqual(bootstrap.targets(home)["pi"], home / "custom/AGENTS.md")


if __name__ == "__main__":
    unittest.main()
