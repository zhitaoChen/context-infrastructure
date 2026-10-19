import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import memory
import knowledge_publication as knowledge


def payload():
    return {"title": "可复用方法", "summary": "先验证，再扩展。", "methods": [{
        "title": "样本先行", "scope": "批量工程任务", "practice": "先用小样本跑通链路，再扩大规模。",
        "verification": "检查真实输出与失败记录。", "limits": "这来自明确工作要求，不是性能提升证明。"}]}


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'AGENTS.md').write_text('fixture')
        self.store = memory.Store(self.root)
        record = {'source': 'PRIVATE_SESSION_SENTINEL', 'observation': '先验证，再扩展。',
                  'evidence': '明确的工作要求。', 'non_sensitive': True, 'durable': True}
        self.key = self.store.capture(record)['id']
        with self.store.connection() as db:
            db.execute("UPDATE candidates SET state='accepted' WHERE id=?", (self.key,))

    def test_export_separates_private_evidence_and_rules(self):
        seen = []
        def model(store, kind, rows):
            seen.append(rows)
            self.assertNotIn('PRIVATE_SESSION_SENTINEL', json.dumps(rows))
            return payload()
        result, artifacts = knowledge.export(self.store, 'daily', model, lambda *args: None)
        self.assertEqual(result['state'], 'exported')
        text = (self.root / result['path']).read_text(encoding='utf-8')
        self.assertNotIn(self.key, text)
        self.assertNotIn('PRIVATE_SESSION_SENTINEL', text)
        self.assertIn('不自动替代现有规则', text)
        self.assertIn(result['path'], artifacts)
        self.assertEqual(knowledge.export(self.store, 'daily', model, lambda *a: None)[0]['state'], 'skipped')

    def test_gate_failure_does_not_write_public_file_or_consume_input(self):
        gate = mock.Mock(side_effect=RuntimeError('blocked'))
        with self.assertRaises(RuntimeError):
            knowledge.export(self.store, 'daily', lambda *a: payload(), gate)
        self.assertFalse((self.root / 'docs/knowledge').exists())
        self.assertEqual(len(knowledge.build_inputs(self.store, 'daily')), 1)

    def test_sensitive_or_invalid_output_blocked(self):
        bad = payload()
        bad['methods'][0]['practice'] = '保存客户资料。'
        with self.assertRaises(ValueError):
            knowledge.validate(bad)
        with self.assertRaises(ValueError):
            knowledge.validate({'title': 'incomplete'})

    def test_weekly_draft_not_marked_applied(self):
        with self.store.connection() as db:
            db.execute("INSERT INTO reviews(id,created,payload) VALUES (?,?,?)",
                       ('review-fixture', memory.now(), json.dumps({'proposals': [{
                           'title': 'abstract', 'proposal': 'method', 'ids': ['private-evidence']}]})))
        result, _ = knowledge.export(self.store, 'weekly', lambda *a: payload(), lambda *a: None)
        self.assertEqual(result['state'], 'exported')
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT state FROM reviews').fetchone()[0], 'pending')


if __name__ == '__main__':
    unittest.main()
