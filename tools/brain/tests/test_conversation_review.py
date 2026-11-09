from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import memory
import conversation_review as review


def row(key, question='请检查实际结果', answer='reply', session='session', digest=None, date='2026-11-09'):
    return {'id': key, 'source': 'pi', 'session_id': session, 'origin': 'fixture',
            'turn_index': int(key), 'turn_time': date + 'T12:00:00+08:00',
            'content_digest': digest or question + answer,
            'user_message': question, 'messages': [{'role': 'user', 'text': question},
                                                   {'role': 'assistant', 'text': answer}]}


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'AGENTS.md').write_text('fixture')
        self.store = memory.Store(self.root)
        self.rows = []
        self.patch1 = mock.patch.object(review.daily, 'load_config', return_value={'enabled': True})
        self.patch2 = mock.patch.object(review.daily, 'snapshot', side_effect=lambda cfg: (self.rows, {}, len(self.rows)))
        self.patch1.start(); self.patch2.start()
        self.addCleanup(self.patch1.stop); self.addCleanup(self.patch2.stop)

    def test_scheduled_prompt_excluded_real_schedule_request_preserved(self):
        auto = row('1', '继续任务#47，先读checkpoint，核对PID，每5分钟自检timer。')
        genuine = row('2', '希望定时检查失败时降低频率，你觉得怎么样？')
        self.assertTrue(review.automated(auto))
        self.assertFalse(review.automated(genuine))
        self.rows = [auto, genuine]
        result = review.prepare(self.store, 1, '2026-11-09')
        self.assertEqual(result['automated_excluded'], 1)
        self.assertEqual(result['pending_unique_real_units'], 1)

    def test_half_hour_operational_marker_requires_all_features(self):
        self.assertTrue(review.automated(row('1', '继续任务#47，先读checkpoint，半小时检查进程。')))
        self.assertFalse(review.automated(row('2', '希望每半小时自检是否合适？先读一下我的计划。')))
        self.assertFalse(review.automated(row('3', '你现在是每半个小时搞一次是吧')))

    def test_no_sixteen_item_daily_limit(self):
        self.rows = [row(str(i), question=f'question {i}') for i in range(1, 81)]
        self.assertEqual(review.prepare(self.store, 1, '2026-11-09')['pending_unique_real_units'], 80)
        self.assertEqual(len(review.show(self.store, 50, 30)), 30)

    def test_repeated_query_different_reply_and_independent_session_preserved(self):
        self.rows = [row('1'), row('2'), row('3', answer='different'), row('4', session='independent')]
        result = review.prepare(self.store, 1, '2026-11-09')
        self.assertEqual(result['pending_unique_real_units'], 3)
        review.commit(self.store, {'decisions': [{'id': '1', 'decision': 'dismiss',
                                                'observations': [], 'reason': 'not_durable'}]})
        result = review.prepare(self.store, 1, '2026-11-09')
        self.assertEqual(result['exact_duplicates_excluded'], 1)
        self.assertEqual(result['pending_unique_real_units'], 2)

    def test_redacted_collision_not_deduplicated(self):
        self.rows = [row('1', digest='original-1'), row('2', digest='original-2')]
        self.assertEqual(review.prepare(self.store, 1, '2026-11-09')['pending_unique_real_units'], 2)

    def test_pinned_day_does_not_consume_other_days(self):
        self.rows = [row('1'), row('2', date='2026-11-08')]
        result = review.prepare(self.store, 1, '2026-11-09')
        self.assertEqual(result['scanned_units'], 1)
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM history_queue').fetchone()[0], 1)

    def test_changed_source_commit_fails_without_consuming(self):
        self.rows = [row('1')]
        review.prepare(self.store, 1, '2026-11-09')
        self.rows = [row('2')]
        with self.assertRaises(ValueError):
            review.commit(self.store, {'decisions': [{'id': '1', 'decision': 'dismiss',
                                                    'observations': [], 'reason': 'not_durable'}]})
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT state FROM history_queue WHERE id='1'").fetchone()[0], 'pending')


if __name__ == '__main__':
    unittest.main()
