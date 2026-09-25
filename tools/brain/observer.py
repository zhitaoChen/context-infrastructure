"""Scheduled extraction of bounded workflow requests; no source-code or tool-output inputs."""

import argparse
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import uuid

if __package__:
    from . import history, memory
else:
    import history
    import memory


MAX_REFERENCES = 16
MAX_SCAN = 5000
AUTOMATED = (
    "[Scheduled prompt", "<system_notification>", "<skill-context",
    "<system-reminder", "<environment_context>", "<user_instructions>",
    "# Daily workflow-memory classifier", "# Weekly workflow-memory reviewer",
    "# Scheduled workflow-memory observer", "Return exactly {",
)
PRIVATE = re.compile(
    r"confidential|proprietary|classified|internal.only|"
    r"机密|保密|内部数据|内部代码|客户资料|密码|密钥|令牌|简历|身份证|护照|签证|"
    r"病历|诊断|宗教|婚姻|工资|薪水|银行账号|银行卡|账户余额|"
    r"我的持仓|我的资产|个人资产|总投入|净利润|盈利|采购|公司注册|"
    r"手机号|电话号码|出生|住址|姓名|我叫|我的名字|税号|移民|"
    r"收入|存款|婚姻|性取向|政治立场|social.security|medical.record|"
    r"bank.account|salary|resume|portfolio|"
    r"\b(?:password|credential|secret|api[_ -]?key|token)\b",
    re.IGNORECASE,
)
CODE_OR_LINK = re.compile(
    r"```|https?://|vc://|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|"
    r"\b[A-Za-z]:[\\/]|(?:^|\s)[.~]?[\\/][\w.-]+[\\/]|"
    r"^\s*(?:import\s|from\s+\w+\s+import|def\s+\w+\(|class\s+\w+|"
    r"SELECT\s+.+\s+FROM|function\s+\w+|curl\s|git\s|pip\s|npm\s|"
    r"(?:const|let|var|public|private|static)\s|#include\s|[A-Za-z_]\w*\s*=\s*)|"
    r"[$¥￥]\s*\d|\d+\s*(?:美元|元|万元|净利润)",
    re.IGNORECASE | re.MULTILINE,
)
WORKFLOW = re.compile(
    r"workflow|pipeline|cross.?check|reproduc|verify|validation|"
    r"skill|axiom|observer|reflector|reflecter|"
    r"以后|今后|每次|规则|公理|工作流|验收|验证|复用|独立|"
    r"交叉|追溯|先.{1,160}再|不要|应该|自动|完整|来源|证据",
    re.IGNORECASE,
)


def unsafe_text(text):
    return bool(memory.SECRET.search(text) or PRIVATE.search(text) or CODE_OR_LINK.search(text))


def failure_detail(exc):
    if isinstance(exc, (ValueError, RuntimeError)):
        return memory.SECRET.sub("[REDACTED]", str(exc))[:1200]
    return f"{type(exc).__name__}; check the local history/configuration and runtime availability"


def select_request(repository, text):
    if not isinstance(text, str) or not text.strip():
        return "dismissed", "not_durable", None
    text = text.strip()
    if text.startswith(AUTOMATED):
        return "dismissed", "out_of_scope", None
    # Non-GitHub/internal repository namespaces require local interactive review.
    if not isinstance(repository, str) or repository.count("/") != 1:
        return "needs_review", "protected_source", None
    if len(text) > 4000:
        return "needs_review", "oversized", None
    if any(ord(c) < 32 and c not in "\n\r\t" for c in text) or unsafe_text(text):
        return "needs_review", "sensitive_or_embedded_content", None
    if not WORKFLOW.search(text):
        return "dismissed", "not_durable", None
    return "model", "", text


def load_config(store):
    path = store.local / "observer.json"
    if not path.exists():
        return None
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    if config.get("version") == 1:
        memory.exact_keys(config, ["version", "enabled", "history_origin",
                                   "max_references", "scan_limit"])
        config = dict(config, history_origins=[config["history_origin"]])
        del config["history_origin"]
        config["version"] = 2
    else:
        memory.exact_keys(config, ["version", "enabled", "history_origins",
                                   "max_references", "scan_limit"])
    if type(config["version"]) is not int or config["version"] != 2 or type(config["enabled"]) is not bool:
        raise ValueError("Unsupported observer configuration")
    if (type(config["max_references"]) is not int or not 1 <= config["max_references"] <= MAX_REFERENCES
            or type(config["scan_limit"]) is not int or not 1 <= config["scan_limit"] <= MAX_SCAN
            or not isinstance(config["history_origins"], list)
            or not config["history_origins"]
            or any(not isinstance(value, str) for value in config["history_origins"])):
        raise ValueError("Invalid observer limits or source")
    return config


def configure(store, confirmed=False):
    if not confirmed:
        raise ValueError("Scheduled extraction requires explicit user authorization")
    with memory.worker_lock(store.local):
        source_origins = history.authorized_origins(store)
        if not source_origins:
            raise ValueError("Configure and enable the approved history source first")
        config = {
            "version": 2, "enabled": True, "history_origins": source_origins,
            "max_references": MAX_REFERENCES, "scan_limit": MAX_SCAN,
        }
        memory.atomic_write(store.local / "observer.json", json.dumps(config, indent=2) + "\n")
    return {"state": "enabled", "mode": "scheduled_workflow_requests",
            "max_references": MAX_REFERENCES, "model": "configured_copilot"}


def select_batch(store, config):
    current_origins = history.authorized_origins(store)
    if set(config["history_origins"]) != set(current_origins):
        raise ValueError("History source changed; explicitly reconfigure the observer")
    placeholders = ",".join("?" for _ in current_origins)
    with store.connection() as db:
        pending = [dict(r) for r in db.execute(
            f"SELECT * FROM history_queue WHERE state='pending' AND origin IN ({placeholders})"
            " ORDER BY turn_time DESC,session_id,turn_index DESC,id LIMIT ?",
            (*current_origins, config["scan_limit"]),
        )]
    inputs, routes = [], []
    for ref in pending:
        row = history.get_turn(store, ref)
        if row is None:
            routes.append((ref, "needs_review", "source_unavailable"))
            continue
        if row["content_digest"] != ref["content_digest"]:
            raise ValueError("History changed after collection; run collection again before extraction")
        state, reason, request = select_request(row["repository"], row["user_message"])
        if state == "model":
            source = f"{row['_source']}-session:{ref['session_id']}"
            inputs.append({"id": ref["id"], "source": source,
                           "request": request, "ref": ref})
            if len(inputs) == config["max_references"]:
                break
        else:
            routes.append((ref, state, reason))
    return inputs, routes


def validate_decisions(payload, inputs):
    memory.exact_keys(payload, ["decisions"])
    if not isinstance(payload["decisions"], list):
        raise ValueError("Observer decisions must be an array")
    expected = {row["id"]: row["ref"] for row in inputs}
    seen, decisions = set(), []
    for item in payload["decisions"]:
        memory.exact_keys(item, ["id", "decision", "observations", "reason"])
        key = item["id"]
        if not isinstance(key, str) or key not in expected or key in seen:
            raise ValueError("Unknown or duplicate observer reference")
        seen.add(key)
        ref = expected[key]
        if item["decision"] == "extract":
            if item["reason"] != "" or not isinstance(item["observations"], list) or not 1 <= len(item["observations"]) <= 2:
                raise ValueError("Extraction requires one or two observations and an empty reason")
            source = next(row["source"] for row in inputs if row["id"] == key)
            prepared = history.prepare_observations(
                ref, {"observations": item["observations"]}, source
            )
            if any(unsafe_text(fields["observation"]) or unsafe_text(fields["evidence"])
                   for _, fields in prepared):
                raise ValueError("Observer output failed the local content boundary; no batch applied")
            decisions.append((ref, "distilled", prepared, ""))
        elif item["decision"] == "dismiss":
            if item["observations"] != [] or item["reason"] not in ("not_durable", "duplicate", "sensitive"):
                raise ValueError("Invalid observer dismissal")
            state = "needs_review" if item["reason"] == "sensitive" else "dismissed"
            decisions.append((ref, state, [], item["reason"]))
        else:
            raise ValueError("Unknown observer decision")
    if seen != set(expected):
        raise ValueError("Every observer input must receive exactly one decision")
    return decisions


def run(store, model=memory.call_copilot):
    with memory.worker_lock(store.local):
        run_id = uuid.uuid4().hex
        with store.connection() as db:
            db.execute("UPDATE runs SET state='interrupted',finished=?,detail=? WHERE state='running'",
                       (memory.now(), "Prior worker exited; observer inputs remain recoverable"))
            db.execute("INSERT INTO runs(id,kind,started,state) VALUES (?,?,?,'running')",
                       (run_id, "observer", memory.now()))
        try:
            config = load_config(store)
            if config is None or not config["enabled"]:
                result = {"state": "skipped", "reason": "Scheduled observer not configured or disabled"}
            else:
                if not history.authorized_origins(store):
                    raise ValueError("Observer enabled but approved history source is disabled")
                inputs, routes = select_batch(store, config)
                decisions = validate_decisions(model(store, "observer", inputs), inputs) if inputs else []
                # Recheck versions after inference; commit all observations and dispositions together.
                for ref, _, _, _ in decisions:
                    history.verify_current_source(store, ref)
                extracted, candidates, held, dismissed = 0, 0, 0, 0
                with store.connection() as db:
                    db.execute("BEGIN IMMEDIATE")
                    for ref, state, reason in routes:
                        if db.execute(
                            "UPDATE history_queue SET state=?,reason=? WHERE id=? AND state='pending'",
                            (state, reason, ref["id"]),
                        ).rowcount != 1:
                            raise ValueError("Observer reference changed before commit")
                        held += state == "needs_review"
                        dismissed += state == "dismissed"
                    for ref, state, prepared, reason in decisions:
                        current = db.execute("SELECT * FROM history_queue WHERE id=?", (ref["id"],)).fetchone()
                        if current is None or current["state"] != "pending":
                            raise ValueError("Observer reference changed before commit")
                        resolution = history.apply_resolution(db, current, state, prepared, reason)
                        extracted += state == "distilled"
                        held += state == "needs_review"
                        dismissed += state == "dismissed"
                        candidates += resolution["inserted_candidates"]
                    remaining = db.execute(
                        "SELECT count(*) FROM history_queue WHERE state='pending'"
                    ).fetchone()[0]
                result = {"state": "success", "model_inputs": len(inputs), "extracted_references": extracted,
                          "candidate_records": candidates, "held_for_review": held,
                          "dismissed": dismissed, "pending_references": remaining}
            store.render()
            with store.connection() as db:
                db.execute("UPDATE runs SET finished=?,state=?,detail=? WHERE id=?",
                           (memory.now(), result["state"], json.dumps(result), run_id))
            return result
        except Exception as exc:
            # Do not persist response bodies or source snippets in an error record.
            with store.connection() as db:
                db.execute("UPDATE runs SET finished=?,state='failed',detail=? WHERE id=?",
                           (memory.now(), failure_detail(exc),
                            run_id))
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=memory.ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("configure")
    setup.add_argument("--confirmed", action="store_true")
    sub.add_parser("run")
    sub.add_parser("disable")
    args = parser.parse_args()
    try:
        store = memory.Store(args.root)
        if args.command == "configure":
            result = configure(store, args.confirmed)
        elif args.command == "run":
            result = run(store)
        else:
            with memory.worker_lock(store.local):
                config = load_config(store)
                if config is None:
                    raise ValueError("Observer is not configured")
                config["enabled"] = False
                memory.atomic_write(store.local / "observer.json", json.dumps(config, indent=2) + "\n")
            result = {"state": "disabled"}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, RuntimeError, OSError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": failure_detail(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
