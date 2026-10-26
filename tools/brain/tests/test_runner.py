"""Exercise the real PowerShell runner with synthetic commands, never a model."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
class RunnerTests(unittest.TestCase):
    def test_concurrent_pipelines_are_serialized_and_failures_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "tools/brain"
            runner = root / "periodic_jobs/ai_heartbeat/run.ps1"
            local = root / "contexts/memory/.local"
            scripts.mkdir(parents=True)
            local.mkdir(parents=True)
            runner.parent.mkdir(parents=True)
            source = Path(__file__).resolve().parents[3] / "periodic_jobs/ai_heartbeat/run.ps1"
            shutil.copyfile(source, runner)
            (local / "config.json").write_text(json.dumps({"python": sys.executable}), encoding="utf-8")
            fixture = '''import pathlib, sys, time
root = pathlib.Path(sys.argv[sys.argv.index('--root') + 1])
with (root / 'events.log').open('a') as f:
    f.write(pathlib.Path(__file__).name + ':' + sys.argv[-1] + '\\n')
time.sleep(0.15)
'''
            for name in ("history.py", "agent_history.py", "observer.py", "memory.py"):
                (scripts / name).write_text(fixture, encoding="utf-8")
            command = [shutil.which("pwsh"), "-NoProfile", "-File", str(runner), "-Kind"]
            first = subprocess.Popen(command + ["daily"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            second = subprocess.Popen(command + ["weekly"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                outputs = [first.communicate(timeout=30), second.communicate(timeout=30)]
                self.assertEqual([first.returncode, second.returncode], [0, 0], outputs)
            finally:
                for process in (first, second):
                    if process.poll() is None:
                        process.kill()
                        process.communicate()
            events = (root / "events.log").read_text().splitlines()
            daily = ["history.py:collect", "agent_history.py:collect", "observer.py:run", "memory.py:daily"]
            weekly = ["history.py:collect", "agent_history.py:collect", "memory.py:weekly"]
            self.assertIn(events, [daily + weekly, weekly + daily])
            (scripts / "history.py").write_text("raise SystemExit(7)", encoding="utf-8")
            failed = subprocess.run(command + ["daily"], capture_output=True, timeout=30)
            self.assertEqual(failed.returncode, 7)
            self.assertEqual((root / "events.log").read_text().splitlines(), events)


if __name__ == "__main__":
    unittest.main()
