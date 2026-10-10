import argparse
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import rewrite


class RewriteTests(unittest.TestCase):
    def setUp(self):
        self.case = {'id': 'test', 'text': '建议暂缓上线。生产尚未验证。', 'units': [
            {'id': 'U1', 'text': '建议暂缓上线。', 'quote': '建议暂缓上线。'},
            {'id': 'U2', 'text': '生产尚未验证。', 'quote': '生产尚未验证。'}]}
        self.judgment = {'units': [
            {'id': 'U1', 'status': 'kept', 'quote': '建议暂缓上线。'},
            {'id': 'U2', 'status': 'kept', 'quote': '生产尚未验证。'}],
            'unlisted': [], 'additions': []}

    def test_rejects_incomplete_duplicate_or_unknown_unit_status(self):
        for mutation in ['drop', 'duplicate', 'status']:
            d = copy.deepcopy(self.judgment)
            if mutation == 'drop':
                d['units'].pop()
            elif mutation == 'duplicate':
                d['units'][1]['id'] = 'U1'
            else:
                d['units'][0]['status'] = 'maybe'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                rewrite.validate_judgment(d, self.case, self.case['text'])

    def test_missing_needs_no_rewrite_quote_but_other_statuses_need_literal_quote(self):
        d = copy.deepcopy(self.judgment)
        d['units'][0].update(status='missing', quote='')
        rewrite.validate_judgment(d, self.case, '生产尚未验证。')
        for status, quote in [('missing', '生产尚未验证。'), ('kept', ''), ('distorted', '已经上线。')]:
            d['units'][0].update(status=status, quote=quote)
            with self.subTest(status=status, quote=quote), self.assertRaises(ValueError):
                rewrite.validate_judgment(d, self.case, self.case['text'])

    def test_unlisted_changes_and_additions_require_quotes_from_correct_source(self):
        d = copy.deepcopy(self.judgment)
        d['unlisted'] = [{'status': 'missing', 'original_quote': '已经上线。', 'quote': ''}]
        with self.assertRaises(ValueError):
            rewrite.validate_judgment(d, self.case, self.case['text'])
        d['unlisted'] = []
        d['additions'] = [{'quote': '建议立即上线。'}]
        with self.assertRaises(ValueError):
            rewrite.validate_judgment(d, self.case, self.case['text'])

    def args(self, root):
        dataset = root / 'data.json'
        conditions = root / 'conditions.json'
        rewrite.engine.save(dataset, [self.case])
        rewrite.engine.save(conditions, [{'id': 'none'}])
        return argparse.Namespace(dataset=str(dataset), conditions=str(conditions), conds=None,
                                  runs=1, judges=['opus'], workers=1, out=str(root / 'out'))

    def test_freeze_prevents_stale_resume_after_source_or_prompt_change(self):
        with tempfile.TemporaryDirectory() as directory:
            a = self.args(Path(directory))
            rewrite.freeze(a)
            changed = copy.deepcopy(self.case)
            changed['text'] += '建议明天讨论。'
            rewrite.engine.save(Path(a.dataset), [changed])
            with self.assertRaises(ValueError):
                rewrite.freeze(a)
            rewrite.engine.save(Path(a.dataset), [self.case])
            with patch.object(rewrite, 'GEN_PROMPT', rewrite.GEN_PROMPT + 'changed'), self.assertRaises(ValueError):
                rewrite.freeze(a)

    def test_incomplete_score_and_tampered_draft_cannot_be_success(self):
        with tempfile.TemporaryDirectory() as directory:
            a = self.args(Path(directory))
            with patch.object(rewrite.engine, 'call', return_value=(self.case['text'], {'models':['test']})):
                rewrite.generate(a)
            with self.assertRaises(FileNotFoundError):
                rewrite.score(a)
            self.assertFalse((Path(a.out) / 'rewrite-summary.json').exists())
            path = Path(a.out) / 'gen/test__none__r1.json'
            draft = rewrite.engine.load(path)
            draft['text'] = '改变内容。'
            rewrite.engine.save(path, draft)
            with self.assertRaises(ValueError):
                rewrite.drafts(a.out, rewrite.manifest(a.out))

    def test_resume_does_not_call_model_and_identity_is_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            a = self.args(Path(directory))
            with patch.object(rewrite.engine, 'call', return_value=(self.case['text'], {'models':['test']})) as model:
                rewrite.generate(a)
                rewrite.generate(a)
                self.assertEqual(model.call_count, 1)
            draft = rewrite.engine.load(Path(a.out) / 'gen/test__identity__r1.json')
            self.assertEqual(draft['text'], self.case['text'])

    def test_generator_is_used_frozen_and_cannot_change_during_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            a = self.args(Path(directory))
            a.generator = 'opus'
            rewrite.engine.save(Path(a.conditions), [{'id': 'none', 'system': '中文文字编辑。'}])
            with patch.object(rewrite.engine, 'call', return_value=(self.case['text'], {'models':['opus']})) as model:
                rewrite.generate(a)
                self.assertEqual(model.call_args.args[0], 'opus')
                self.assertEqual(model.call_args.kwargs['system'], '中文文字编辑。')
            self.assertEqual(rewrite.manifest(a.out)['generator'], 'opus')
            a.generator = 'sonnet'
            with self.assertRaisesRegex(ValueError, '运行配置改变'):
                rewrite.generate(a)


if __name__ == '__main__':
    unittest.main()
