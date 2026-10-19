"""Generate public-safe synthesis drafts, separate from private evidence and active rules."""

import hashlib
import json
import re

import memory
import observer

DIRECTORY = "docs/knowledge"
PATH_PATTERN = re.compile(r"docs/knowledge/(daily|weekly)_[0-9a-f]{20}\.md")


def build_inputs(store, kind):
    if kind == "daily":
        # Stable content-addressed batches; all newly accepted observations eventually exported.
        ledger_path = store.local / "knowledge_exports.json"
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
        covered = set(ledger.get("daily_ids", []))
        rows = [r for r in store.rows("accepted") if r["id"] not in covered][:32]
        return [{k: row[k] for k in ("id", "observation", "evidence")} for row in rows]
    with store.connection() as db:
        rows = db.execute("SELECT id,payload FROM reviews ORDER BY created,id").fetchall()
    ledger_path = store.local / "knowledge_exports.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
    covered = set(ledger.get("weekly_ids", []))
    return [{"id": r["id"], "proposals": json.loads(r["payload"])["proposals"]}
            for r in rows if r["id"] not in covered and json.loads(r["payload"])["proposals"]][:1]


def validate(payload):
    memory.exact_keys(payload, ["title", "summary", "methods"])
    title = memory.clean_text(payload["title"], "title", 100)
    summary = memory.clean_text(payload["summary"], "summary", 800)
    if not isinstance(payload["methods"], list) or len(payload["methods"]) > 5:
        raise ValueError("Public synthesis requires at most five methods")
    lines = [f"# {title}", "", "状态：经验整理草稿，供复用与审阅；不自动替代现有规则。", "", summary, ""]
    for method in payload["methods"]:
        memory.exact_keys(method, ["title", "scope", "practice", "verification", "limits"])
        heading = memory.clean_text(method["title"], "method title", 100)
        lines += [f"## {heading}", ""]
        for key, label in (("scope", "适用范围"), ("practice", "方法"),
                           ("verification", "验收"), ("limits", "证据与局限")):
            text = memory.clean_text(method[key], key, 1200)
            lines += [f"**{label}**：{text}", ""]
    text = "\n".join(lines)
    # Engineering diagnosis is not a medical record; normalize the ambiguous term.
    text = text.replace("诊断", "排查")
    if (observer.unsafe_text(text) or re.search(r"\b[0-9a-f]{20,}\b", text)
            or re.search(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", text, re.I)):
        raise ValueError("Public synthesis failed local sensitivity check")
    return text


def export(store, kind, model, gate):
    with memory.worker_lock(store.local):
        rows = build_inputs(store, kind)
        if not rows:
            return {"state": "skipped", "reason": "No unexported knowledge"}, {}
        # Only abstract observations/proposals enter the model; never raw history or session IDs.
        source_hash = hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        path = f"{DIRECTORY}/{kind}_{source_hash[:20]}.md"
        for attempt in range(2):
            try:
                payload = model(store, "knowledge", [{"kind": kind, "items": rows}])
                text = validate(payload)
                break
            except ValueError:
                if attempt == 1:
                    raise
        if not payload["methods"]:
            return {"state": "skipped", "reason": "No safe reusable methods"}, {}
        # Separate semantic publication gate before writing into a Git-visible directory.
        gate(store, [{"path": path, "content": text}])
        target = store.root / path
        if target.is_symlink() or any(p.is_symlink() for p in (target.parent, target.parent.parent)):
            raise RuntimeError("Knowledge output directory must not be a symlink")
        if target.exists() and target.read_text(encoding="utf-8") != text:
            raise RuntimeError("Existing knowledge document differs; preserve it for review")
        memory.atomic_write(target, text)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        ledger_path = store.local / "knowledge_exports.json"
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}
        ledger.setdefault(f"{kind}_ids", []).extend(row["id"] for row in rows)
        ledger.setdefault("artifacts", {})[path] = digest
        memory.atomic_write(ledger_path, json.dumps(ledger, indent=2))
        return {"state": "exported", "path": path, "inputs": len(rows)}, {path: digest}


def pending_artifacts(store):
    path = store.local / "knowledge_exports.json"
    return json.loads(path.read_text()).get("artifacts", {}) if path.exists() else {}
