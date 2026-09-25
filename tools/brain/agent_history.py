"""Read-only Claude Code and Codex history references; never persist raw conversations."""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import uuid

if __package__:
    from . import memory
else:
    import memory


SOURCES = ("claude", "codex")
MAX_TURNS = 5000
SESSION_ID = re.compile(r"[\w-]{1,120}")
GENERATED_CLAUDE_PREFIXES = (
    "<command-name>", "<command-message>", "<local-command-caveat>",
    "<local-command-stdout>", "<task-notification>", "<ide_opened_file>",
    "<system-reminder>", "<environment_context>", "<user_instructions>",
    "<skill-context",
)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def utc_time(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def default_roots(source):
    if source == "claude":
        return [Path.home() / ".claude" / "projects"]
    if source == "codex":
        return [Path.home() / ".codex" / "sessions",
                Path.home() / ".codex" / "archived_sessions"]
    raise ValueError(f"Unsupported agent history source: {source}")


def load_config(store):
    path = store.local / "agent_history.json"
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    memory.exact_keys(value, ["version", "enabled", "sources", "since"])
    if value["version"] != 1 or type(value["enabled"]) is not bool:
        raise ValueError("Unsupported agent history configuration")
    if (not isinstance(value["sources"], dict) or not value["sources"]
            or any(source not in SOURCES for source in value["sources"])):
        raise ValueError("Agent history sources must contain Claude Code and/or Codex")
    for roots in value["sources"].values():
        if (not isinstance(roots, list) or not roots
                or any(not isinstance(root, str) or not Path(root).is_absolute() for root in roots)):
            raise ValueError("Agent history roots must be nonempty absolute path lists")
    if utc_time(value["since"]) is None:
        raise ValueError("Agent history since must be an ISO timestamp")
    return value


def configure(store, sources, backfill_days, confirmed=False, replace=False):
    if not confirmed:
        raise ValueError("Agent history scope and backfill require explicit user confirmation")
    if (not isinstance(sources, list) or not sources
            or len(set(sources)) != len(sources) or any(source not in SOURCES for source in sources)):
        raise ValueError("Choose one or more supported agent history sources")
    if type(backfill_days) is not int or not 0 <= backfill_days <= 3650:
        raise ValueError("backfill_days must be between 0 and 3650")
    path = store.local / "agent_history.json"
    with memory.worker_lock(store.local):
        if path.exists() and not replace:
            raise ValueError("Agent history is already configured; use --replace after reviewing scope")
        roots = {source: [str(root.resolve()) for root in default_roots(source)]
                 for source in sources}
        if not any(Path(root).is_dir() for values in roots.values() for root in values):
            raise ValueError("None of the approved agent history directories exist")
        config = {
            "version": 1,
            "enabled": True,
            "sources": roots,
            "since": (datetime.now(timezone.utc) - timedelta(days=backfill_days)).isoformat(),
        }
        memory.atomic_write(path, json.dumps(config, indent=2) + "\n")
    return {"state": "configured", "sources": sources, "since": config["since"],
            "mode": "references_only_scheduled_distillation"}


def origin_id(config, source):
    roots = [os.path.normcase(str(Path(root).resolve())) for root in config["sources"][source]]
    return digest(["agent-history", source, roots, config["since"]])


def origins(config):
    if config is None or not config["enabled"]:
        return {}
    return {origin_id(config, source): source for source in config["sources"]}


def extract_text(content):
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n\n".join(parts)


def iter_jsonl(roots, pattern):
    files = set()
    for root_text in roots:
        root = Path(root_text)
        if root.is_dir():
            files.update(root.rglob(pattern))
    return sorted(files)


def claude_rows(roots):
    for path in iter_jsonl(roots, "*.jsonl"):
        if "subagents" in path.parts:
            continue
        rows = []
        session_id = ""
        cwd = ""
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict) or event.get("isSidechain") is True:
                    continue
                session_id = event.get("sessionId") or session_id
                cwd = event.get("cwd") or cwd
                if event.get("type") != "user":
                    continue
                text = extract_text((event.get("message") or {}).get("content"))
                stamp = utc_time(event.get("timestamp"))
                if (text and stamp
                        and not text.lstrip().lower().startswith(GENERATED_CLAUDE_PREFIXES)):
                    rows.append((text, stamp))
        if isinstance(session_id, str) and SESSION_ID.fullmatch(session_id):
            for index, (text, stamp) in enumerate(rows):
                yield make_row("claude", session_id, index, stamp, text, cwd)


def codex_item_text(item):
    if not isinstance(item, dict):
        return ""
    parts = []
    for entry in item.get("content") or []:
        if isinstance(entry, dict):
            text = entry.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n".join(parts)


def codex_rows(roots):
    for path in iter_jsonl(roots, "rollout-*.jsonl"):
        rows = []
        session_id = ""
        cwd = ""
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                payload = event.get("payload")
                if not isinstance(payload, dict):
                    continue
                event_type = event.get("type")
                if event_type == "session_meta":
                    session_id = str(payload.get("id") or payload.get("session_id") or session_id)
                    cwd = str(payload.get("cwd") or cwd)
                    continue
                if event_type == "turn_context":
                    cwd = str(payload.get("cwd") or cwd)
                    continue
                if event_type != "event_msg":
                    continue
                payload_type = payload.get("type")
                if payload_type == "user_message":
                    text = str(payload.get("message") or "").strip()
                elif payload_type == "item_completed":
                    item = payload.get("item")
                    text = codex_item_text(item) if isinstance(item, dict) and item.get("type") == "UserMessage" else ""
                else:
                    text = ""
                stamp = utc_time(event.get("timestamp"))
                if text and stamp:
                    rows.append((text, stamp))
        if SESSION_ID.fullmatch(session_id):
            for index, (text, stamp) in enumerate(rows):
                yield make_row("codex", session_id, index, stamp, text, cwd)


def make_row(source, session_id, index, stamp, text, cwd):
    return {
        "source": source,
        "session_id": session_id,
        "turn_index": index,
        "timestamp": stamp.isoformat(),
        "user_message": text,
        "repository": None,
        "cwd": cwd if isinstance(cwd, str) else "",
        "content_digest": digest([text]),
    }


def scan_rows(config):
    rows = []
    for source, roots in config["sources"].items():
        iterator = claude_rows(roots) if source == "claude" else codex_rows(roots)
        rows.extend(iterator)
    rows.sort(key=lambda row: (row["timestamp"], row["source"],
                               row["session_id"], row["turn_index"]))
    return rows


def reference(config, row):
    origin = origin_id(config, row["source"])
    return {
        "id": digest([origin, row["session_id"], row["turn_index"], row["content_digest"]]),
        "origin": origin,
        "session_id": row["session_id"],
        "turn_index": row["turn_index"],
        "turn_time": row["timestamp"],
        "content_digest": row["content_digest"],
    }


def collect_batch(store, config, maximum):
    since = utc_time(config["since"])
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=2)
    rows = [row for row in scan_rows(config)
            if since <= utc_time(row["timestamp"]) <= cutoff]
    result = {"state": "success", "scanned": len(rows), "queued": 0,
              "superseded": 0, "more": False, "sources": {}}
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        actions = []
        for row in rows:
            ref = reference(config, row)
            current = db.execute("SELECT state FROM history_queue WHERE id=?", (ref["id"],)).fetchone()
            if current is None or current["state"] == "superseded":
                actions.append((row, ref))
        result["more"] = len(actions) > maximum
        for row, ref in actions[:maximum]:
            result["superseded"] += db.execute(
                "UPDATE history_queue SET state='superseded' WHERE origin=?"
                " AND session_id=? AND turn_index=? AND id<>?"
                " AND state IN ('pending','needs_review')",
                (ref["origin"], ref["session_id"], ref["turn_index"], ref["id"]),
            ).rowcount
            existing = db.execute("SELECT state FROM history_queue WHERE id=?", (ref["id"],)).fetchone()
            if existing is None:
                db.execute(
                    "INSERT INTO history_queue"
                    "(id,origin,session_id,turn_index,turn_time,content_digest,created)"
                    " VALUES (:id,:origin,:session_id,:turn_index,:turn_time,:content_digest,:created)",
                    dict(ref, created=memory.now()),
                )
            else:
                db.execute("UPDATE history_queue SET state='pending' WHERE id=?", (ref["id"],))
            result["queued"] += 1
            result["sources"][row["source"]] = result["sources"].get(row["source"], 0) + 1
    return result


def collect(store, maximum=MAX_TURNS):
    if type(maximum) is not int or not 1 <= maximum <= 10000:
        raise ValueError("max-turns must be between 1 and 10000")
    with memory.worker_lock(store.local):
        run_id = uuid.uuid4().hex
        with store.connection() as db:
            db.execute("INSERT INTO runs(id,kind,started,state) VALUES (?,?,?,'running')",
                       (run_id, "agent-history", memory.now()))
        try:
            config = load_config(store)
            if config is None or not config["enabled"]:
                result = {"state": "skipped", "reason": "Agent history not configured or disabled"}
            else:
                result = collect_batch(store, config, maximum)
            store.render()
            with store.connection() as db:
                db.execute("UPDATE runs SET finished=?,state=?,detail=? WHERE id=?",
                           (memory.now(), result["state"], json.dumps(result), run_id))
            return result
        except Exception as exc:
            with store.connection() as db:
                db.execute("UPDATE runs SET finished=?,state='failed',detail=? WHERE id=?",
                           (memory.now(), memory.SECRET.sub("[REDACTED]", str(exc))[:1600], run_id))
            raise


def get_turn(store, ref):
    config = load_config(store)
    if config is None or not config["enabled"]:
        return None
    source = origins(config).get(ref["origin"])
    if source is None:
        return None
    for row in scan_rows({"sources": {source: config["sources"][source]},
                          "since": config["since"]}):
        if row["session_id"] == ref["session_id"] and row["turn_index"] == ref["turn_index"]:
            return row
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=memory.ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("configure")
    setup.add_argument("--source", action="append", choices=SOURCES, required=True)
    setup.add_argument("--backfill-days", type=int, default=0)
    setup.add_argument("--confirmed", action="store_true")
    setup.add_argument("--replace", action="store_true")
    scan = sub.add_parser("collect")
    scan.add_argument("--max-turns", type=int, default=MAX_TURNS)
    sub.add_parser("disable")
    args = parser.parse_args()
    try:
        store = memory.Store(args.root)
        if args.command == "configure":
            result = configure(store, args.source, args.backfill_days, args.confirmed, args.replace)
        elif args.command == "collect":
            result = collect(store, args.max_turns)
        else:
            with memory.worker_lock(store.local):
                config = load_config(store)
                if config is None:
                    raise ValueError("Agent history is not configured")
                config["enabled"] = False
                memory.atomic_write(store.local / "agent_history.json",
                                    json.dumps(config, indent=2) + "\n")
            result = {"state": "disabled"}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"error": memory.SECRET.sub("[REDACTED]", str(exc))}, ensure_ascii=False),
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
