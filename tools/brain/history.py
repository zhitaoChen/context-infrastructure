"""Read-only Copilot history references; never send raw conversations to a model."""

import argparse
from contextlib import contextmanager
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


DEFAULT_DATABASE = Path.home() / ".copilot" / "session-store.db"
REFERENCE_FIELDS = "id,session_id,turn_index,turn_time,state"
MAX_TURNS = 5000


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def utc_time(value):
    if not isinstance(value, str):
        raise ValueError("History timestamps must be strings")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_config(store):
    path = store.local / "history.json"
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    memory.exact_keys(value, ["version", "enabled", "database", "repositories", "since"])
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("Unsupported history configuration version")
    if type(value["enabled"]) is not bool:
        raise ValueError("History enabled must be a boolean")
    if not isinstance(value["database"], str) or not Path(value["database"]).is_absolute():
        raise ValueError("History database must be an absolute path")
    repositories = value["repositories"]
    if (not isinstance(repositories, list) or not repositories
            or any(not isinstance(r, str) or not re.fullmatch(r"[\w.-]+/[\w.-]+|\*", r)
                   for r in repositories)
            or ("*" in repositories and repositories != ["*"])):
        raise ValueError("Choose explicit owner/repository names, or ['*'] for all repositories")
    utc_time(value["since"])
    return value


@contextmanager
def source_connection(config):
    path = Path(config["database"])
    # mode=ro must not create an empty database if the history path is wrong.
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA query_only=ON")
        for table, required in (
            ("sessions", {"id", "repository"}),
            ("turns", {"id", "session_id", "turn_index", "timestamp",
                       "user_message", "assistant_response"}),
        ):
            columns = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
            if not required <= columns:
                raise ValueError("Unsupported Copilot local history schema; no inputs consumed")
        db.execute("BEGIN")
        yield db
    finally:
        db.close()


def origin_id(config):
    return digest(os.path.normcase(str(Path(config["database"]).resolve())))


def scope_sql(config):
    clause = "s.repository IS NOT NULL AND trim(s.repository) <> ''"
    params = []
    if config["repositories"] != ["*"]:
        clause += " AND lower(s.repository) IN (" + ",".join(
            "?" for _ in config["repositories"]
        ) + ")"
        params = [r.lower() for r in config["repositories"]]
    return clause, params


def turn_digest(row):
    return digest([row["user_message"], row["assistant_response"]])


def reference(origin, row):
    if (not isinstance(row["session_id"], str)
            or not re.fullmatch(r"[\w-]{1,120}", row["session_id"])
            or type(row["turn_index"]) is not int or row["turn_index"] < 0
            or type(row["id"]) is not int or row["id"] < 1):
        raise ValueError("Unsupported history turn identifier; no inputs consumed")
    content_digest = turn_digest(row)
    return {
        "id": digest([origin, row["session_id"], row["turn_index"], content_digest]),
        "origin": origin, "session_id": row["session_id"], "turn_index": row["turn_index"],
        "turn_time": utc_time(row["timestamp"]).isoformat(), "content_digest": content_digest,
    }


def configure(store, database, repositories, backfill_days, confirmed=False, replace=False):
    if not confirmed:
        raise ValueError("History scope and backfill require explicit user confirmation")
    if type(backfill_days) is not int or not 0 <= backfill_days <= 3650:
        raise ValueError("backfill_days must be between 0 and 3650")
    path = store.local / "history.json"
    with memory.worker_lock(store.local):
        if path.exists() and not replace:
            raise ValueError("History is already configured; use --replace after reviewing scope")
        config = {
            "version": 1, "enabled": True, "database": str(Path(database).resolve()),
            "repositories": repositories,
            "since": (datetime.now(timezone.utc) - timedelta(days=backfill_days)).isoformat(),
        }
        # Validate before replacing any existing configuration.
        if (not repositories or any(not isinstance(r, str)
                or not re.fullmatch(r"[\w.-]+/[\w.-]+|\*", r) for r in repositories)
                or ("*" in repositories and repositories != ["*"])):
            raise ValueError("Invalid repository scope")
        with source_connection(config):
            pass
        memory.atomic_write(path, json.dumps(config, indent=2) + "\n")
    return {"state": "configured", "mode": "references_only_interactive_distillation",
            "all_repositories": repositories == ["*"], "since": config["since"]}


def collect_batch(store, config, maximum):
    origin = origin_id(config)
    scan_key = digest([origin, config["repositories"], config["since"]])
    scope, params = scope_sql(config)
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    result = {"state": "success", "scanned": 0, "new_scanned": 0, "reconciled": 0,
              "queued": 0, "superseded": 0,
              "empty_user_turns": 0, "more": False}
    with source_connection(config) as source, store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        cursor = db.execute(
            "SELECT last_turn_id,high_watermark FROM history_cursors WHERE scan_key=?", (scan_key,)
        ).fetchone()
        after = cursor["last_turn_id"] if cursor else 0
        high = cursor["high_watermark"] if cursor else 0
        # A replaced/truncated local source must not strand the scan above its highest ID.
        highest = source.execute("SELECT coalesce(max(id),0) FROM turns").fetchone()[0]
        if high > highest or after > highest:
            after = 0
            high = 0

        def enqueue(row):
            ref = reference(origin, row)
            result["scanned"] += 1
            # Late assistant updates get a new version; only unresolved old versions are retired.
            result["superseded"] += db.execute(
                "UPDATE history_queue SET state='superseded' WHERE origin=?"
                " AND session_id=? AND turn_index=? AND id<>? AND state IN ('pending','needs_review')",
                (origin, ref["session_id"], ref["turn_index"], ref["id"]),
            ).rowcount
            if not isinstance(row["user_message"], str) or not row["user_message"].strip():
                result["empty_user_turns"] += 1
                return
            existing = db.execute("SELECT state FROM history_queue WHERE id=?", (ref["id"],)).fetchone()
            if existing is None:
                db.execute(
                    "INSERT INTO history_queue"
                    "(id,origin,session_id,turn_index,turn_time,content_digest,created)"
                    " VALUES (:id,:origin,:session_id,:turn_index,:turn_time,:content_digest,:created)",
                    dict(ref, created=memory.now()),
                )
                result["queued"] += 1
            elif existing["state"] == "superseded":
                db.execute("UPDATE history_queue SET state='pending' WHERE id=?", (ref["id"],))
                result["queued"] += 1

        def scan(start, end, budget):
            rows = source.execute(
                "SELECT t.id,t.session_id,t.turn_index,t.timestamp,t.user_message,t.assistant_response"
                " FROM turns t JOIN sessions s ON s.id=t.session_id"
                " WHERE t.id>? AND t.id<=? AND julianday(t.timestamp)>=julianday(?)"
                " AND julianday(t.timestamp)<=julianday(?) AND " + scope +
                " ORDER BY t.id LIMIT ?",
                [start, end, config["since"], cutoff, *params, budget + 1],
            )
            count, last = 0, start
            for row in rows:
                if count == budget:
                    return count, last, True
                enqueue(row)
                count += 1
                last = row["id"]
            return count, last, False

        # Prioritize appended turns so old-version reconciliation cannot delay new work.
        new_count, next_high, new_more = scan(high, highest, maximum)
        result["new_scanned"] = new_count
        result["more"] = new_more
        if not new_more and high:
            count, after, old_more = scan(after, high, maximum - new_count)
            result["reconciled"] = count
            result["more"] = old_more
            if not old_more:
                after = 0
        db.execute(
            "INSERT INTO history_cursors(scan_key,last_turn_id,high_watermark,updated) VALUES (?,?,?,?)"
            " ON CONFLICT(scan_key) DO UPDATE SET last_turn_id=excluded.last_turn_id,"
            " high_watermark=excluded.high_watermark,"
            " updated=excluded.updated",
            (scan_key, after, next_high if new_more else highest, memory.now()),
        )
    return result


def collect(store, maximum=MAX_TURNS):
    if type(maximum) is not int or not 1 <= maximum <= 10000:
        raise ValueError("max-turns must be between 1 and 10000")
    with memory.worker_lock(store.local):
        run_id = uuid.uuid4().hex
        with store.connection() as db:
            db.execute("UPDATE runs SET state='interrupted',finished=?,detail=? WHERE state='running'",
                       (memory.now(), "Prior worker exited; history queue and cursor are recoverable"))
            db.execute("INSERT INTO runs(id,kind,started,state) VALUES (?,?,?,'running')",
                       (run_id, "history", memory.now()))
        try:
            config = load_config(store)
            if config is None or not config["enabled"]:
                result = {"state": "skipped", "reason": "History collection not configured or disabled"}
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


def list_pending(store, limit=20, session=None, state="pending"):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if state not in ("pending", "needs_review"):
        raise ValueError("History list state must be pending or needs_review")
    query = f"SELECT {REFERENCE_FIELDS},reason FROM history_queue WHERE state=?"
    params = [state]
    if session is not None:
        query += " AND session_id=?"
        params.append(session)
    query += " ORDER BY turn_time,session_id,turn_index,id LIMIT ?"
    with store.connection() as db:
        return [dict(row) for row in db.execute(query, [*params, limit])]


def verify_current_source(store, ref):
    config = load_config(store)
    if config is None or not config["enabled"] or origin_id(config) != ref["origin"]:
        raise ValueError("Reference is outside the currently enabled history source")
    scope, params = scope_sql(config)
    with source_connection(config) as source:
        row = source.execute(
            "SELECT t.* FROM turns t JOIN sessions s ON s.id=t.session_id"
            " WHERE t.session_id=? AND t.turn_index=? AND julianday(t.timestamp)>=julianday(?)"
            " AND " + scope,
            [ref["session_id"], ref["turn_index"], config["since"], *params],
        ).fetchone()
        if row is None or turn_digest(row) != ref["content_digest"]:
            raise ValueError("Source turn is missing, changed or outside scope; collect and review again")


def prepare_observations(ref, payload):
    memory.exact_keys(payload, ["observations"])
    observations = payload["observations"]
    if not isinstance(observations, list) or not 1 <= len(observations) <= 8:
        raise ValueError("Distillation requires one to eight reviewed observations")
    prepared = []
    for item in observations:
        memory.exact_keys(item, ["observation", "evidence", "non_sensitive", "durable"])
        prepared.append(memory.prepare_record(
            dict(item, source=f"copilot-session:{ref['session_id']}")
        ))
    if len({p[0] for p in prepared}) != len(prepared):
        raise ValueError("Duplicate observations in a distillation batch")
    return prepared


def apply_resolution(db, ref, decision, prepared, reason):
    ids = [p[0] for p in prepared]
    key = ref["id"]
    if ref["state"] not in ("pending", "needs_review"):
        if (ref["state"] == decision and json.loads(ref["candidate_ids"]) == ids
                and ref["reason"] == reason):
            return {"state": decision, "id": key, "candidate_ids": ids, "already_resolved": True,
                    "inserted_candidates": 0}
        raise ValueError("Reference was superseded or already resolved differently")
    inserted = 0
    for candidate_id, fields in prepared:
        inserted += db.execute(
            "INSERT OR IGNORE INTO candidates(id,created,source,observation,evidence)"
            " VALUES (?,?,?,?,?)",
            (candidate_id, memory.now(), fields["source"], fields["observation"], fields["evidence"]),
        ).rowcount
    db.execute("UPDATE history_queue SET state=?,candidate_ids=?,reason=? WHERE id=?",
               (decision, json.dumps(ids), reason, key))
    return {"state": decision, "id": key, "candidate_ids": ids, "already_resolved": False,
            "inserted_candidates": inserted}


def resolve(store, key, decision, payload=None, reason="", confirmed=False):
    if not confirmed:
        raise ValueError("Interactive review and privacy/durability confirmation are required")
    if decision not in ("distilled", "dismissed"):
        raise ValueError("History decision must be distilled or dismissed")
    if decision == "dismissed" and reason not in ("sensitive", "not_durable", "duplicate", "out_of_scope"):
        raise ValueError("Dismissal requires a supported reason code")
    if decision == "distilled" and reason:
        raise ValueError("Distillation must not include a dismissal reason")
    with memory.worker_lock(store.local):
        with store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            ref = db.execute("SELECT * FROM history_queue WHERE id=?", (key,)).fetchone()
            if ref is None:
                raise ValueError("Unknown history reference")
            prepared = prepare_observations(ref, payload) if decision == "distilled" else []
            if decision == "distilled" and ref["state"] in ("pending", "needs_review"):
                verify_current_source(store, ref)
            result = apply_resolution(db, ref, decision, prepared, reason)
        store.render()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=memory.ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("configure")
    setup.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    scope = setup.add_mutually_exclusive_group(required=True)
    scope.add_argument("--all-repositories", action="store_true")
    scope.add_argument("--repository", action="append")
    setup.add_argument("--backfill-days", type=int, default=0)
    setup.add_argument("--confirmed", action="store_true")
    setup.add_argument("--replace", action="store_true")
    scan = sub.add_parser("collect")
    scan.add_argument("--max-turns", type=int, default=MAX_TURNS)
    listing = sub.add_parser("list")
    listing.add_argument("--limit", type=int, default=20)
    listing.add_argument("--session")
    listing.add_argument("--state", choices=("pending", "needs_review"), default="pending")
    review = sub.add_parser("resolve")
    review.add_argument("--id", required=True)
    review.add_argument("--decision", choices=("distilled", "dismissed"), required=True)
    review.add_argument("--reason", default="")
    review.add_argument("--confirmed", action="store_true")
    sub.add_parser("disable")
    args = parser.parse_args()
    try:
        store = memory.Store(args.root)
        if args.command == "configure":
            result = configure(store, args.database, ["*"] if args.all_repositories else args.repository,
                               args.backfill_days, args.confirmed, args.replace)
        elif args.command == "collect":
            result = collect(store, args.max_turns)
        elif args.command == "list":
            result = {"references": list_pending(store, args.limit, args.session, args.state)}
        elif args.command == "resolve":
            payload = json.loads(sys.stdin.read(16385)) if args.decision == "distilled" else None
            result = resolve(store, args.id, args.decision, payload, args.reason, args.confirmed)
        else:
            with memory.worker_lock(store.local):
                config = load_config(store)
                if config is None:
                    raise ValueError("History is not configured")
                config["enabled"] = False
                memory.atomic_write(store.local / "history.json", json.dumps(config, indent=2) + "\n")
            result = {"state": "disabled"}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"error": memory.SECRET.sub("[REDACTED]", str(exc))}, ensure_ascii=False),
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
