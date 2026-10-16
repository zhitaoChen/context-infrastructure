from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_history
import conversation_daily as daily
import conversation_privacy as privacy
import memory


def stamp():
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'AGENTS.md').write_text('fixture')
        self.store = memory.Store(self.root)
        self.sessions = self.root / 'sessions'
        self.sessions.mkdir()
        self.config = {'version': 1, 'enabled': True, 'since': '1970-01-01T00:00:00+00:00',
                       'sources': {'pi': [str(self.sessions)]},
                       'copilot_database': str(self.root / 'missing.db'),
                       'max_batches': 8, 'batch_size': 16}
        memory.atomic_write(self.store.local / 'conversation_daily.json', json.dumps(self.config))

    def write(self, user='每次先验证结果，再说明完成。', answer='The approach was corrected.'):
        events = [
            {'type': 'session', 'version': 3, 'id': 'fixture-session', 'cwd': 'private'},
            {'type': 'message', 'id': 'u', 'parentId': None, 'timestamp': stamp(),
             'message': {'role': 'user', 'content': user}},
            {'type': 'message', 'id': 'a', 'parentId': 'u', 'timestamp': stamp(),
             'message': {'role': 'assistant', 'stopReason': 'stop', 'content': [
                 {'type': 'thinking', 'thinking': 'HIDDEN_REASONING'},
                 {'type': 'text', 'text': answer}]}},
            {'type': 'message', 'id': 't', 'parentId': 'a', 'timestamp': stamp(),
             'message': {'role': 'toolResult', 'content': 'HIDDEN_TOOL_OUTPUT'}},
        ]
        (self.sessions / 'fixture.jsonl').write_text(
            ''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in events), encoding='utf-8')

    def model(self, store, kind, rows):
        self.assertEqual(kind, 'conversation')
        return {'decisions': [{'id': r['id'], 'decision': 'extract', 'reason': '',
            'observations': [{'observation': '完成声明之前核验真实输出。',
                              'evidence': '用户明确提出先验证再说明完成的要求。',
                              'non_sensitive': True, 'durable': True}]} for r in rows]}

    def test_partial_redaction_preserves_query(self):
        text = '每次先验证结果。password=do-not-send；我的工资是很多元。然后再说明完成。'
        clean = privacy.redact(text)
        self.assertNotIn('do-not-send', clean)
        self.assertNotIn('工资', clean)
        self.assertIn('先验证结果', clean)
        self.assertIn('再说明完成', clean)
        self.assertIn('[', clean)

    def test_private_key_body_redacted(self):
        clean = privacy.redact('先验证。-----BEGIN PRIVATE KEY-----\nPRIVATE_BODY\n-----END PRIVATE KEY-----。再检查。')
        self.assertNotIn('PRIVATE_BODY', clean)
        self.assertIn('再检查', clean)

    def test_code_path_contact_redaction(self):
        clean = privacy.redact('先检查。```python\nprint("PRIVATE")\n```\n然后验证。'
                               ' https://example.invalid/private a@example.invalid C:\\private\\file')
        for value in ('PRIVATE', 'example.invalid', 'C:\\private'):
            self.assertNotIn(value, clean)
        self.assertIn('然后验证', clean)

    def test_assistant_text_no_tools_or_thinking(self):
        self.write()
        rows, _, _ = daily.snapshot(self.config)
        encoded = json.dumps(rows)
        self.assertNotIn('HIDDEN_REASONING', encoded)
        self.assertNotIn('HIDDEN_TOOL_OUTPUT', encoded)
        self.assertIn('approach was corrected', encoded)

    def test_branch_pairing(self):
        self.write()
        path = self.sessions / 'fixture.jsonl'
        events = [
            {'type': 'message', 'id': 'v', 'parentId': 'u', 'timestamp': stamp(),
             'message': {'role': 'user', 'content': '第二个分支的用户请求'}},
            {'type': 'message', 'id': 'b', 'parentId': 'v', 'timestamp': stamp(),
             'message': {'role': 'assistant', 'content': 'BRANCH_B_REPLY'}},
        ]
        with path.open('a', encoding='utf-8') as f:
            for e in events:
                f.write(json.dumps(e) + '\n')
        rows = agent_history.scan_rows(self.config, include_assistant=True)
        first = next(r for r in rows if r['user_message'].startswith('每次'))
        self.assertNotIn('BRANCH_B_REPLY', first['assistant_response'])

    def test_real_chain_idempotent_and_raw_not_persisted(self):
        self.write('每次先验证结果。password=RAW_CREDENTIAL_SENTINEL；然后说明完成。')
        seen = []
        def model(store, kind, rows):
            seen.extend(rows)
            self.assertNotIn('RAW_CREDENTIAL_SENTINEL', json.dumps(rows))
            return self.model(store, kind, rows)
        result = daily.run(self.store, model)
        self.assertEqual(result['candidates'], 1)
        self.assertEqual(daily.run(self.store, model)['processed'], 0)
        self.assertEqual(len(seen), 1)
        for p in self.store.local.rglob('*'):
            if p.is_file():
                self.assertNotIn(b'RAW_CREDENTIAL_SENTINEL', p.read_bytes())

    def test_long_query_is_chunked_not_dropped(self):
        self.write('先验证结果。' * 7000)
        rows, _, turns = daily.snapshot(self.config)
        self.assertEqual(turns, 1)
        self.assertGreater(len(rows), 1)
        self.assertEqual(sum(len(m['text']) for r in rows for m in r['messages'] if m['role']=='user'),
                         len('先验证结果。' * 7000))

    def test_failure_preserves_pending(self):
        self.write()
        with self.assertRaises(RuntimeError):
            daily.run(self.store, mock.Mock(side_effect=RuntimeError('failure')))
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM history_queue WHERE state='pending'").fetchone()[0], 1)
        self.assertEqual(daily.run(self.store, self.model)['processed'], 1)

    def test_output_sensitive_candidate_does_not_poison_entire_batch(self):
        self.write()
        def model(store, kind, rows):
            result = self.model(store, kind, rows)
            result['decisions'][0]['observations'].append({
                'observation': '保留客户资料以便以后核验。', 'evidence': '用户要求。',
                'non_sensitive': True, 'durable': True})
            return result
        self.assertEqual(daily.run(self.store, model)['candidates'], 1)

    def test_nonrepository_copilot_session_included(self):
        from contextlib import closing
        import sqlite3
        path = self.root / 'copilot.db'
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript('CREATE TABLE sessions(id TEXT,repository TEXT,cwd TEXT);'
                             'CREATE TABLE turns(id INTEGER,session_id TEXT,turn_index INTEGER,'
                             'timestamp TEXT,user_message TEXT,assistant_response TEXT);')
            db.execute('INSERT INTO sessions VALUES (?,?,?)', ('no-repo', None, 'private'))
            db.execute('INSERT INTO turns VALUES (?,?,?,?,?,?)',
                       (1, 'no-repo', 0, stamp(), '每次先验证。', 'Assistant reply.'))
        self.config['copilot_database'] = str(path)
        rows, coverage = daily.scan(self.config)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['assistant_response'], 'Assistant reply.')
        self.assertEqual(coverage['copilot'], 'available')

    def test_assistant_update_invalidates_reference(self):
        self.write()
        first = daily.snapshot(self.config)[0][0]['id']
        self.write(answer='Changed response')
        second = daily.snapshot(self.config)[0][0]['id']
        self.assertNotEqual(first, second)


if __name__ == '__main__':
    unittest.main()
