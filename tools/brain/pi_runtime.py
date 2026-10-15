"""Restricted Pi JSON-mode model adapter; no tools, history, or context discovery."""

import json
import os
import subprocess

import memory

TEMPLATES = {"daily": "daily_observer.md", "weekly": "weekly_reflector.md",
             "observer": "history_observer.md", "publication": "publication_review.md"}


def parse_output(text):
    answer = None
    settled = False
    # JSONL is delimited by LF, not Unicode line/paragraph separators.
    for line in text.split("\n"):
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("type", "").startswith("tool_execution_"):
            raise ValueError("Restricted Pi attempted a tool call")
        if event.get("type") == "message_end":
            message = event.get("message", {})
            if message.get("role") == "assistant":
                content = message.get("content", [])
                if any(block.get("type") == "toolCall" for block in content):
                    raise ValueError("Restricted Pi requested a tool")
                if message.get("stopReason") != "stop":
                    raise RuntimeError("Pi response failed, aborted, or was truncated")
                answer = "".join(block["text"] for block in content
                                 if block.get("type") == "text")
        if event.get("type") == "agent_settled":
            settled = event.get("aborted") is False
    if not settled or answer is None:
        raise RuntimeError("Pi did not produce a successful settled result")
    if answer.startswith("```json\n") and answer.rstrip().endswith("```"):
        answer = answer[8:].rstrip()[:-3].strip()
    return json.loads(answer)


def load_config(store):
    return json.loads((store.local / "pi_runtime.json").read_text(encoding="utf-8-sig"))


def call_pi(store, kind, rows):
    config = load_config(store)
    template = store.root / "periodic_jobs/ai_heartbeat/prompts" / TEMPLATES[kind]
    if kind == "publication":
        inputs = rows
    else:
        fields = ("id", "source", "request") if kind == "observer" else (
            "id", "source", "observation", "evidence")
        inputs = [{key: row[key] for key in fields} for row in rows]
    prompt = template.read_text(encoding="utf-8") + "\nINPUT_JSON:\n" + json.dumps(
        inputs, ensure_ascii=False)
    command = config["pi_command"] + [
        "--mode", "json", "--no-session", "--no-tools", "--no-extensions", "--no-mcp",
        "--no-skills", "--no-prompt-templates", "--no-themes", "--no-context-files",
        "--no-approve", "--offline", "--provider", config["provider"],
        "--model", config["model"], "--thinking", "low",
        "--system-prompt", "Classify supplied data only. Return the requested JSON. No tools.",
    ]
    env = os.environ.copy()
    env["PI_CODING_AGENT_DIR"] = config["agent_dir"]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, cwd=store.local, env=env,
                               text=True, encoding="utf-8", start_new_session=os.name != "nt")
    try:
        stdout, _ = process.communicate(prompt, timeout=config["timeout_seconds"])
    except subprocess.TimeoutExpired as exc:
        try:
            memory.stop_process_tree(process)
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
        raise RuntimeError("Pi timed out; no model decisions applied") from exc
    if process.returncode:
        # Do not expose input context, credentials or provider diagnostics in task output.
        raise RuntimeError(f"Pi failed with exit {process.returncode}; diagnostics withheld")
    return parse_output(stdout)
