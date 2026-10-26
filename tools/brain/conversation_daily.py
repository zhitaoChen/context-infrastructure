"""Opt-in redacted conversation distillation; raw text never persisted or logged."""

from datetime import datetime, timedelta, timezone
import argparse
import json
import uuid

try:
    from . import agent_history, conversation_privacy as privacy, history, memory, observer
except ImportError:
    import agent_history
    import conversation_privacy as privacy
    import history
    import memory
    import observer


def configure(store, confirmed=False):
    if not confirmed:
        raise ValueError("Conversation processing requires explicit user authorization")
    config = {"version": 1, "enabled": True, "since": "1970-01-01T00:00:00+00:00",
              "sources": {source: [str(p.resolve()) for p in agent_history.default_roots(source)]
                          for source in agent_history.SOURCES},
              "copilot_database": str(history.DEFAULT_DATABASE.resolve()),
              "max_batches": 8, "batch_size": 16}
    with memory.worker_lock(store.local):
        if (store.local / "conversation_daily.json").exists():
            raise ValueError("Conversation config already exists; review it locally instead of overwriting")
        memory.atomic_write(store.local / "conversation_daily.json", json.dumps(config, indent=2))
    return {"state": "configured", "mode": "redacted_user_and_assistant",
            "sources": ["copilot", *agent_history.SOURCES]}


def load_config(store):
    path = store.local / "conversation_daily.json"
    if not path.exists():
        return None
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    memory.exact_keys(config, ["version", "enabled", "since", "sources", "copilot_database",
                               "max_batches", "batch_size"])
    if (config["version"] != 1 or type(config["enabled"]) is not bool
            or type(config["max_batches"]) is not int or not 1 <= config["max_batches"] <= 8
            or type(config["batch_size"]) is not int or not 1 <= config["batch_size"] <= 16):
        raise ValueError("Invalid conversation processing limits")
    if set(config["sources"]) - set(agent_history.SOURCES):
        raise ValueError("Unsupported conversation source")
    return config


def scan(config):
    coverage = {name: ("available" if any(memory.Path(p).is_dir() for p in roots)
                       else "not_found") for name, roots in config["sources"].items()}
    # This runtime registers optional standard locations, unlike the strict reference collector.
    # Preserve authorization and report missing sources without blocking available ones.
    available = {name: roots for name, roots in config["sources"].items()
                 if coverage[name] == "available"}
    rows = agent_history.scan_rows(dict(config, sources=available), include_assistant=True)
    path = memory.Path(config["copilot_database"])
    coverage["copilot"] = "available" if path.is_file() else "not_found"
    if path.is_file():
        with history.source_connection({"database": str(path)}) as db:
            # Explicit all-history authorization includes sessions without a repository tag.
            for record in db.execute("SELECT t.*,s.cwd FROM turns t JOIN sessions s ON s.id=t.session_id"):
                row = dict(record)
                row["source"] = "copilot"
                row["content_digest"] = history.turn_digest(row)
                rows.append(row)
    since = history.utc_time(config["since"])
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=2)
    result = []
    for row in rows:
        if (isinstance(row.get("user_message"), str) and row["user_message"].strip()
                and since <= history.utc_time(row["timestamp"]) <= cutoff):
            row["origin"] = agent_history.digest(["redacted-conversation-v1", row["source"],
                config["sources"].get(row["source"], config["copilot_database"])])
            row["id"] = agent_history.digest([row["origin"], row["session_id"],
                                               row["turn_index"], row["content_digest"]])
            row["turn_time"] = history.utc_time(row["timestamp"]).isoformat()
            result.append(row)
    return sorted(result, key=lambda r: (r["turn_time"], r["id"])), coverage


def excerpts(row):
    user = row["user_message"].strip()
    if user.startswith(observer.AUTOMATED) or user.lower().startswith(agent_history.GENERATED_CLAUDE_PREFIXES):
        return []
    messages = [("user", user), ("assistant", row.get("assistant_response") or "")]
    result = []
    for role, text in messages:
        # Redact the complete text BEFORE splitting so a secret cannot straddle chunks.
        for index, chunk in enumerate(privacy.chunks(privacy.redact(text))):
            if chunk.strip():
                result.append({"role": role, "part": index, "text": chunk})
    return result


def snapshot(config):
    rows, coverage = scan(config)
    units = []
    for row in rows:
        messages = excerpts(row)
        groups = [[]]
        size = 0
        for message in messages:
            count = len(message["text"])
            if groups[-1] and size + count > 12000:
                groups.append([])
                size = 0
            groups[-1].append(message)
            size += count
        for index, group in enumerate(groups):
            unit = dict(row, messages=group)
            unit["turn_index"] = int(agent_history.digest([row["turn_index"], index])[:15], 16)
            unit["id"] = agent_history.digest([row["id"], index])
            units.append(unit)
    return units, coverage, len(rows)


def validate_output(payload, batch):
    memory.exact_keys(payload, ["decisions"])
    if not isinstance(payload["decisions"], list):
        raise ValueError("Conversation decisions must be an array")
    safe = []
    for item in payload["decisions"]:
        memory.exact_keys(item, ["id", "decision", "observations", "reason"])
        if item["decision"] == "extract" and isinstance(item["observations"], list):
            kept = []
            for observation in item["observations"]:
                memory.exact_keys(observation, ["observation", "evidence", "non_sensitive", "durable"])
                memory.prepare_record(dict(observation, source="validation"))
                if not (observer.unsafe_text(observation["observation"])
                        or observer.unsafe_text(observation["evidence"])):
                    kept.append(observation)
            if item["observations"] and not kept:
                item = dict(item, decision="dismiss", observations=[], reason="sensitive")
            elif kept:
                item = dict(item, observations=kept)
        safe.append(item)
    return observer.validate_decisions({"decisions": safe}, batch)


def run(store, model):
    config = load_config(store)
    if config is None or not config["enabled"]:
        return {"state": "skipped", "reason": "Conversation distillation not configured"}
    with memory.worker_lock(store.local):
        run_id = uuid.uuid4().hex
        with store.connection() as db:
            db.execute("INSERT INTO runs(id,kind,started,state) VALUES (?,?,?,'running')",
                       (run_id, "conversation", memory.now()))
        try:
            rows, coverage, available_turns = snapshot(config)
            origins = {r["origin"] for r in rows}
            lookup = {row["id"]: row for row in rows}
            with store.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                for row in rows:
                    db.execute("UPDATE history_queue SET state='superseded' WHERE origin=? AND session_id=?"
                               " AND turn_index=? AND id<>? AND state IN ('pending','needs_review')",
                               (row["origin"], row["session_id"], row["turn_index"], row["id"]))
                    db.execute("INSERT OR IGNORE INTO history_queue"
                               "(id,origin,session_id,turn_index,turn_time,content_digest,created)"
                               " VALUES (?,?,?,?,?,?,?)", tuple(row[k] for k in (
                                   "id", "origin", "session_id", "turn_index", "turn_time", "content_digest"))
                               + (memory.now(),))
                pending = [dict(r) for r in db.execute(
                    "SELECT * FROM history_queue WHERE state='pending' ORDER BY turn_time DESC,id")
                           if r["id"] in lookup]
                for ref in db.execute("SELECT id,origin FROM history_queue WHERE state='pending'"):
                    if ref["origin"] in origins and ref["id"] not in lookup:
                        db.execute("UPDATE history_queue SET state='superseded' WHERE id=?", (ref["id"],))
            inputs = []
            dismissed = 0
            for ref in pending:
                row = lookup[ref["id"]]
                messages = row["messages"]
                if not messages:
                    with store.connection() as db:
                        db.execute("UPDATE history_queue SET state='dismissed',reason='out_of_scope' WHERE id=?",
                                   (ref["id"],))
                    dismissed += 1
                    continue
                inputs.append({"id": ref["id"], "source": f"{row['source']}-session:{row['session_id']}",
                               "messages": messages, "ref": ref})
            processed = extracted = candidates = batches = 0
            while inputs and batches < config["max_batches"]:
                batch = []
                size = 0
                while inputs and len(batch) < config["batch_size"]:
                    count = len(json.dumps(inputs[0]["messages"]))
                    if batch and size + count > 60000:
                        break
                    batch.append(inputs.pop(0))
                    size += count
                attempts = 0
                while True:
                    attempts += 1
                    try:
                        decisions = validate_output(model(store, "conversation", batch), batch)
                        break
                    except ValueError:
                        if attempts >= 2:
                            raise
                # Re-read original sources after inference; no stale evidence is consumed.
                current = {r["id"] for r in snapshot(config)[0]}
                stale = [ref["id"] for ref, _, _, _ in decisions if ref["id"] not in current]
                if stale:
                    with store.connection() as db:
                        db.executemany("UPDATE history_queue SET state='superseded' WHERE id=?", [(k,) for k in stale])
                    raise ValueError("Conversation changed during inference; recollect before retry")
                with store.connection() as db:
                    db.execute("BEGIN IMMEDIATE")
                    for ref, state, prepared, reason in decisions:
                        existing = db.execute("SELECT * FROM history_queue WHERE id=?", (ref["id"],)).fetchone()
                        if existing["state"] != "pending":
                            raise ValueError("Conversation reference changed before commit")
                        resolution = history.apply_resolution(db, existing, state, prepared, reason)
                        candidates += resolution["inserted_candidates"]
                        extracted += state == "distilled"
                processed += len(batch)
                batches += 1
            result = {"state": "success", "coverage": coverage, "available_turns": available_turns,
                      "processed": processed, "extracted": extracted, "candidates": candidates,
                      "automated_dismissed": dismissed, "remaining": len(inputs), "batches": batches}
            store.render()
            with store.connection() as db:
                db.execute("UPDATE runs SET finished=?,state='success',detail=? WHERE id=?",
                           (memory.now(), json.dumps(result), run_id))
            return result
        except Exception as exc:
            with store.connection() as db:
                db.execute("UPDATE runs SET finished=?,state='failed',detail=? WHERE id=?",
                           (memory.now(), type(exc).__name__, run_id))
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=memory.Path, default=memory.ROOT)
    parser.add_argument("command", choices=("configure", "status", "disable"))
    parser.add_argument("--confirmed", action="store_true")
    args = parser.parse_args()
    store = memory.Store(args.root)
    if args.command == "configure":
        result = configure(store, args.confirmed)
    else:
        config = load_config(store)
        if args.command == "disable" and config is not None:
            with memory.worker_lock(store.local):
                config["enabled"] = False
                memory.atomic_write(store.local / "conversation_daily.json", json.dumps(config, indent=2))
        result = {"configured": config is not None, "enabled": bool(config and config["enabled"])}
        if config and args.command == "status":
            _, coverage = scan(config)
            result["coverage"] = coverage
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
