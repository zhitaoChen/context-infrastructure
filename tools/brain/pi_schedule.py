"""Daily/weekly Pi memory maintenance and fail-closed public Git synchronization."""

import argparse
import hashlib
import json
import os
from pathlib import PurePosixPath
import subprocess
import sys

import memory
import pi_runtime
import conversation_daily
import knowledge_publication

ROOT_FILES = {"AGENTS.md", "README.md", "setup_guide.md", ".gitignore",
              ".pi-loop.config.json", "pyrightconfig.json"}
PREFIXES = ("rules/", "docs/", "tools/brain/", "periodic_jobs/ai_heartbeat/", "integrations/")


def allowed_path(path):
    parts = PurePosixPath(path).parts
    return (bool(parts) and not any(p in ("..", "archive", ".local", "__pycache__")
                                    or (p.startswith(".") and p not in ROOT_FILES) for p in parts)
            and not any(p.lower() in ("user.local.md", "auth.json", "models.json", "config.json")
                        for p in parts)
            and (path in ROOT_FILES or path.startswith(PREFIXES))
            and PurePosixPath(path).suffix.lower() in (".md", ".py", ".ps1", ".json", ".ts", ""))


def git(root, *args, data=None):
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(["git", "-C", str(root), *args], input=data,
                            capture_output=True, env=env, timeout=120)
    if result.returncode:
        raise RuntimeError(f"Git {args[0]} failed (exit {result.returncode}); inspect locally")
    return result.stdout


def review_publication(store, rows, model=pi_runtime.call_pi):
    payload = model(store, "publication", rows)
    memory.exact_keys(payload, ["decisions"])
    expected = {row["path"] for row in rows}
    seen = set()
    if not isinstance(payload["decisions"], list):
        raise ValueError("Publication decisions must be an array")
    for decision in payload["decisions"]:
        memory.exact_keys(decision, ["path", "safe"])
        path = decision["path"]
        if not isinstance(path, str) or path not in expected or path in seen:
            raise ValueError("Unknown or duplicate publication path")
        if decision["safe"] is not True:
            raise RuntimeError("Publication blocked: sensitive or uncertain file; review locally")
        seen.add(path)
    if seen != expected:
        raise ValueError("Publication review omitted files")


def sync_public(store, config, dry_run=False, model=pi_runtime.call_pi, generated=None):
    root = store.root
    branch = config["branch"]
    if git(root, "branch", "--show-current").decode().strip() != branch:
        raise RuntimeError("Publication blocked: checkout is not the configured branch")
    if git(root, "remote", "get-url", "--push", "origin").decode().strip() != config["remote"]:
        raise RuntimeError("Publication blocked: remote changed")
    if git(root, "diff", "--cached", "--name-only", "-z"):
        raise RuntimeError("Publication blocked: existing staged user changes")
    git(root, "fetch", "origin", f"refs/heads/{branch}")
    remote_head = git(root, "rev-parse", "FETCH_HEAD").decode().strip()
    head = git(root, "rev-parse", "HEAD").decode().strip()
    state_path = store.local / "pi_publication.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    # Only retry a commit produced by this runner. Never push unreviewed local history.
    if head != remote_head:
        if (state.get("pending_commit") != head or state.get("base") != remote_head
                or state.get("validated") is not True):
            raise RuntimeError("Publication blocked: local/remote history differs; reconcile manually")
        if not dry_run:
            git(root, "push", "origin", f"{head}:refs/heads/{branch}")
            memory.atomic_write(state_path, json.dumps({"last_pushed": head}))
        return {"state": "retry_pending" if dry_run else "pushed", "commit": head}
    names = git(root, "diff", "--name-only", "-z", "HEAD").decode("utf-8").split("\0")
    paths = [path for path in names if path and allowed_path(path)]
    # Only exact, gated, content-hash-bound knowledge artifacts may be new files.
    generated = generated or {}
    for path, expected_digest in generated.items():
        if not knowledge_publication.PATH_PATTERN.fullmatch(path):
            raise ValueError("Invalid generated knowledge path")
        target = root / path
        if target.is_symlink() or not target.is_file() or any(
                p.is_symlink() for p in (target.parent, target.parent.parent)):
            raise RuntimeError("Generated knowledge must be a regular file")
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected_digest:
            raise RuntimeError("Generated knowledge changed after validation")
        if not git(root, "ls-files", "--", path) and path not in paths:
            paths.append(path)
    if not paths:
        return {"state": "skipped", "reason": "No eligible tracked changes"}
    rows = []
    fingerprints = {}
    expected_blobs = {}
    for path in paths:
        target = root / path
        entry = git(root, "ls-files", "-s", "--", path).decode()
        if (not entry and path in generated):
            pass
        elif not entry.startswith("100644 ") and not entry.startswith("100755 "):
            raise RuntimeError("Publication blocked: symlink, submodule or nonregular file")
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise RuntimeError("Publication blocked: nonregular working file")
        content = target.read_bytes() if target.exists() else b""
        if len(content) > 100_000:
            raise RuntimeError("Publication blocked: file exceeds review bound")
        text = content.decode("utf-8-sig")
        if "\0" in text or memory.SECRET.search(text):
            raise RuntimeError("Publication blocked: binary data or possible credentials")
        diff = git(root, "diff", "HEAD", "--", path).decode("utf-8")
        rows.append({"path": path, "content": text, "diff": diff})
        fingerprints[path] = (target.exists(), hashlib.sha256(content).hexdigest())
        expected_blobs[path] = ({
            git(root, "hash-object", f"--path={path}", "--stdin", data=content).decode().strip(),
            git(root, "hash-object", "--no-filters", "--stdin", data=content).decode().strip(),
        } if target.exists() else {None})
    if sum(len(json.dumps(row)) for row in rows) > 160_000:
        raise RuntimeError("Publication blocked: batch exceeds review bound")
    review_publication(store, rows, model)
    if dry_run:
        return {"state": "preview", "paths": paths}
    for path, (existed, digest) in fingerprints.items():
        target = root / path
        content = target.read_bytes() if target.exists() else b""
        if target.exists() != existed or hashlib.sha256(content).hexdigest() != digest:
            raise RuntimeError("Publication blocked: reviewed file changed")
    if git(root, "rev-parse", "HEAD").decode().strip() != head:
        raise RuntimeError("Publication blocked: HEAD changed during review")
    if git(root, "diff", "--cached", "--name-only", "-z"):
        raise RuntimeError("Publication blocked: index changed during review")
    # --only excludes other staged files; never git add -A / force-push / auto-rebase.
    new_paths = [path for path in paths if not git(root, "ls-files", "--", path)]
    if new_paths:
        git(root, "add", "-N", "--", *new_paths)
    git(root, "commit", "--only", "-m", f"chore(brain): public knowledge sync {memory.now()[:10]}",
        "--", *paths)
    committed = git(root, "rev-parse", "HEAD").decode().strip()
    memory.atomic_write(state_path, json.dumps({"pending_commit": committed, "base": head}))
    # Revalidate exact committed bytes before the external side effect.
    committed_paths = set(git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z",
                              committed).decode("utf-8").strip("\0").split("\0"))
    if committed_paths != set(paths) or git(root, "rev-parse", f"{committed}^").decode().strip() != head:
        raise RuntimeError("Publication blocked: commit scope or parent changed")
    for path, expected_blob in expected_blobs.items():
        entry = git(root, "ls-tree", committed, "--", path).decode().strip()
        blob = entry.split()[2] if entry else None
        if blob not in expected_blob or (entry and not entry.startswith(("100644 ", "100755 "))):
            raise RuntimeError("Publication blocked: committed content differs from reviewed snapshot")
    memory.atomic_write(state_path, json.dumps({"pending_commit": committed, "base": head,
                                               "validated": True}))
    git(root, "push", "origin", f"{committed}:refs/heads/{branch}")
    memory.atomic_write(state_path, json.dumps({"last_pushed": committed}))
    return {"state": "pushed", "commit": committed, "paths": paths}


def run(store, kind, dry_run=False):
    config = pi_runtime.load_config(store)
    with memory.worker_lock(store.local / "pi_scheduler"):
        if dry_run:
            return {"publication": sync_public(store, config, dry_run=True)}
        # Only explicitly configured sources may enter the redacted distillation pipeline.
        result = {}
        if kind == "daily":
            result["conversation"] = conversation_daily.run(store, pi_runtime.call_pi)
        result["memory"] = memory.run_worker(store, kind, model=pi_runtime.call_pi)
        result["knowledge"], _ = knowledge_publication.export(
            store, kind, pi_runtime.call_pi, review_publication)
        result["publication"] = sync_public(
            store, config, generated=knowledge_publication.pending_artifacts(store))
        memory.atomic_write(store.local / f"pi_{kind}_result.json",
                            json.dumps({"finished": memory.now(), **result}, ensure_ascii=False, indent=2))
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=memory.Path, default=memory.ROOT)
    parser.add_argument("--kind", choices=("daily", "weekly"), required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    store = memory.Store(args.root)
    try:
        result = run(store, args.kind, args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        # Only an exception class goes into unattended logs; inspect failures locally.
        memory.atomic_write(store.local / f"pi_{args.kind}_result.json",
                            json.dumps({"finished": memory.now(), "state": "failed",
                                        "error_type": type(exc).__name__}))
        print(f"Pi maintenance failed ({type(exc).__name__}); inspect locally", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
