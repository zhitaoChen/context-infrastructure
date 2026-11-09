"""Local triage and transaction API for in-session conversation review; no model calls."""

import argparse
from collections import Counter
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import uuid

try:
    from . import conversation_daily as daily, history, memory, observer
except ImportError:
    import conversation_daily as daily
    import history
    import memory
    import observer

# Explicit recurring operational prompts, not arbitrary mentions of schedules.
OPERATIONAL = re.compile(
    r"^(?:继续(?:当前新todo|main-placement|完成A组|#\d+|todo\d+)|"
    r"仅运行个人PiXP实验组|推进Mixed/dev300|main-placement-v3两小时服务恢复探测|"
    r"每半小时持续推进|持续推进C2实验|自检提示词分层实验任务|"
    r"每(?:5|10|30)分钟(?:review|检查|推进)|在当前 Pi 会话执行本仓库知识维护|"
    r"每次本定时触发|继续任务#|每半小时自检|检查并用中文主动报告个人PiXP|"
    r"继续用户授权的GenSERP部署评测|继续600Query|检查verified部署重试|继续完成用户授权的GenSERP闭环)"
)
TIMER = re.compile(r"timer|定时|自检|半小时|\d+\s*(?:分钟|小时|min)", re.I)
STATE = re.compile(r"checkpoint|检查点|PID|进程|读取|先读", re.I)


def automated(row):
    text = row['user_message'].strip()
    if text.startswith(observer.AUTOMATED) or text.lower().startswith(daily.agent_history.GENERATED_CLAUDE_PREFIXES):
        return True
    return bool(OPERATIONAL.search(text) and TIMER.search(text) and STATE.search(text))


def signature(row):
    # Deduplicate exact original Q+A versions within a session, never redacted text alone.
    # Separate chunks and differing assistant replies remain independently reviewable.
    return (row['source'], row['session_id'], row['content_digest'],
            hashlib.sha256(json.dumps(row['messages'], sort_keys=True).encode()).hexdigest())


def enqueue(store, rows):
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        for row in rows:
            db.execute("UPDATE history_queue SET state='superseded' WHERE origin=? AND session_id=?"
                       " AND turn_index=? AND id<>? AND state IN ('pending','needs_review')",
                       (row['origin'], row['session_id'], row['turn_index'], row['id']))
            db.execute('INSERT OR IGNORE INTO history_queue'
                       '(id,origin,session_id,turn_index,turn_time,content_digest,created) VALUES (?,?,?,?,?,?,?)',
                       tuple(row[k] for k in ('id','origin','session_id','turn_index','turn_time','content_digest'))
                       + (memory.now(),))


def prepare(store, days=21, target_date=None):
    if not 1 <= days <= 3650:
        raise ValueError('Invalid review window')
    config = daily.load_config(store)
    if not config or not config['enabled']:
        raise ValueError('Existing conversation authorization must be enabled')
    today = datetime.now(memory.CST).date()
    end_date = datetime.fromisoformat(target_date).date() if target_date else today
    if end_date > today:
        raise ValueError('Review date cannot be in the future')
    since = end_date - timedelta(days=days - 1)
    with memory.worker_lock(store.local):
        rows, coverage, turns = daily.snapshot(config)
        rows = [r for r in rows if since <= history.utc_time(r['turn_time']).astimezone(memory.CST).date() <= end_date]
        rows.sort(key=lambda r: (r['turn_time'], r['id']))
        enqueue(store, rows)
        with store.connection() as db:
            states = {r['id']: r['state'] for r in db.execute('SELECT id,state FROM history_queue')}
        seen = {}
        routes = []
        for row in rows:
            if automated(row) or not row['messages']:
                if states[row['id']] == 'pending':
                    routes.append((row, 'out_of_scope'))
                continue
            key = signature(row)
            if key in seen:
                first = seen[key]
                # Do not consume a duplicate until the retained representative is reviewed.
                if states[first['id']] in ('distilled', 'dismissed') and states[row['id']] == 'pending':
                    routes.append((row, 'duplicate'))
            else:
                seen[key] = row
        result = {'automated_excluded': 0, 'exact_duplicates_excluded': 0}
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            for row, reason in routes:
                ref = db.execute('SELECT * FROM history_queue WHERE id=?', (row['id'],)).fetchone()
                history.apply_resolution(db, ref, 'dismissed', [], reason)
                result['automated_excluded' if reason == 'out_of_scope' else 'exact_duplicates_excluded'] += 1
            remaining = {r['id']: r['state'] for r in db.execute('SELECT id,state FROM history_queue')}
        items = [r for r in seen.values() if remaining[r['id']] == 'pending']
        by_day = Counter(history.utc_time(r['turn_time']).astimezone(memory.CST).date().isoformat() for r in items)
        manifest = {'version': 1, 'since': since.isoformat(), 'target_date': end_date.isoformat(),
                    'scanned_at': memory.now(), 'ids': [r['id'] for r in items],
                    'coverage': coverage, 'days': dict(sorted(by_day.items())), **result}
        memory.atomic_write(store.local / 'session_review_manifest.json', json.dumps(manifest, indent=2))
        store.render()
        return {'window_start': since.isoformat(), 'target_date': end_date.isoformat(),
                'scanned_at': manifest['scanned_at'], 'scanned_units': len(rows), 'available_turns': turns,
                'real_unique_total': len(seen),
                'real_representatives_already_reviewed': sum(remaining[r['id']] in ('distilled', 'dismissed') for r in seen.values()),
                'held_for_review': sum(remaining[r['id']] == 'needs_review' for r in seen.values()),
                'pending_unique_real_units': len(items), 'coverage': coverage, 'days': dict(sorted(by_day.items())), **result}


def show(store, offset=0, limit=20):
    if offset < 0 or not 1 <= limit <= 50:
        raise ValueError('Invalid page')
    manifest = json.loads((store.local / 'session_review_manifest.json').read_text())
    config = daily.load_config(store)
    if not config or not config['enabled']:
        raise ValueError('Conversation authorization disabled')
    lookup = {r['id']: r for r in daily.snapshot(config)[0]}
    result = []
    for key in manifest['ids'][offset:offset + limit]:
        if key not in lookup:
            raise ValueError('Source changed; prepare a new manifest')
        row = lookup[key]
        result.append({'id': key, 'day': history.utc_time(row['turn_time']).astimezone(memory.CST).date().isoformat(),
                       'messages': row['messages']})
    return result


def commit(store, payload):
    config = daily.load_config(store)
    if not config or not config['enabled']:
        raise ValueError('Conversation authorization disabled')
    manifest = json.loads((store.local / 'session_review_manifest.json').read_text())
    allowed = set(manifest['ids'])
    with memory.worker_lock(store.local):
        lookup = {r['id']: r for r in daily.snapshot(config)[0]}
        batch = []
        for item in payload['decisions']:
            key = item['id']
            if key not in allowed or key not in lookup:
                raise ValueError('Unreviewed or changed source ID')
            row = lookup[key]
            with store.connection() as db:
                ref = dict(db.execute('SELECT * FROM history_queue WHERE id=?', (key,)).fetchone())
            batch.append({'id': key, 'source': f"{row['source']}-session:{row['session_id']}", 'ref': ref})
        decisions = daily.validate_output(payload, batch)
        current = {r['id'] for r in daily.snapshot(config)[0]}
        if any(ref['id'] not in current for ref, _, _, _ in decisions):
            raise ValueError('Source changed during review')
        counts = Counter()
        run_id = uuid.uuid4().hex
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            for ref, state, prepared, reason in decisions:
                live = db.execute('SELECT * FROM history_queue WHERE id=?', (ref['id'],)).fetchone()
                if live['state'] != 'pending':
                    raise ValueError('Source already consumed')
                counts['candidates'] += history.apply_resolution(db, live, state, prepared, reason)['inserted_candidates']
                counts[state] += 1
            result = {'state': 'success', 'mode': 'current_session_review', 'processed': len(decisions), **counts}
            db.execute('INSERT INTO runs(id,kind,started,finished,state,detail) VALUES (?,?,?,?,?,?)',
                       (run_id, 'conversation', memory.now(), memory.now(), 'success', json.dumps(result)))
        store.render()
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'show', 'commit'))
    parser.add_argument('--days', type=int, default=21)
    parser.add_argument('--date', help='Pinned Beijing target date YYYY-MM-DD')
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--limit', type=int, default=20)
    args = parser.parse_args()
    store = memory.Store(memory.ROOT)
    if args.command == 'prepare':
        result = prepare(store, args.days, args.date)
    elif args.command == 'show':
        result = show(store, args.offset, args.limit)
    else:
        import sys
        result = commit(store, json.load(sys.stdin))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
