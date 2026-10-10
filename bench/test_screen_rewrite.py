import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import screen_rewrite as screen


class ScreenTests(unittest.TestCase):
    def test_equal_length_clarity_improvement_is_evaluated_and_old_results_are_preserved(self):
        original = '本轮未验证，不能发布。'
        text = '本轮没验证，不可发布。'
        self.assertEqual(screen.readable_chars(original), screen.readable_chars(text))
        case = {'text':original,'units':[{'id':'U1'}]}
        draft = dict(cond='candidate',text=text,text_hash=screen.rewrite.digest(text),reader='工程师')
        label = 'A' if int(draft['text_hash'][0],16)%2 else 'B'
        fidelity = dict(units=[dict(id='U1',status='kept',quote=text)],unlisted=[],additions=[])
        quality = dict(clarity=label,naturalness='same',concision='same',structure='same',preferred=label,gain='clear',note='指代与条件更清楚',a_quote=original if label=='B' else text,b_quote=text if label=='B' else original)
        with tempfile.TemporaryDirectory() as directory:
            old = Path(directory)/'screen-v1/summary.json'
            screen.rewrite.engine.save(old,{'keep':'历史结果'})
            previous = Path(directory)/'screen-v2/summary.json'
            screen.rewrite.engine.save(previous,{'keep':'未检查结构的历史结果'})
            with patch.object(screen.rewrite,'manifest',return_value={'hash':'fixed'}), patch.object(screen.rewrite,'drafts',return_value=[('sample',case,draft)]), patch.object(screen.rewrite.engine,'call',side_effect=[(json.dumps(fidelity),{}),(json.dumps(quality),{})]) as model:
                self.assertEqual(screen.screen(directory)[0]['status'],'ready_for_primary_fidelity')
                self.assertEqual(model.call_count,2)
            self.assertEqual(screen.rewrite.engine.load(old),{'keep':'历史结果'})
            self.assertEqual(screen.rewrite.engine.load(previous),{'keep':'未检查结构的历史结果'})

    def test_unchanged_and_longer_drafts_do_not_call_judges(self):
        case = {'text':'生产尚未验证。'}
        for text,status in [(case['text'],'unchanged'),('生产环境尚未验证。','rejected_length_increase')]:
            draft = dict(cond='candidate',text=text,text_hash=screen.rewrite.digest(text))
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                with patch.object(screen.rewrite,'manifest',return_value={'hash':'fixed'}), patch.object(screen.rewrite,'drafts',return_value=[('sample',case,draft)]), patch.object(screen.rewrite.engine,'call') as model:
                    self.assertEqual(screen.screen(directory)[0]['status'],status)
                    model.assert_not_called()

    def test_screen_rejects_loss_and_fails_closed_on_tampered_cached_evidence(self):
        case = {'text': '生产环境尚未验证。重复：生产环境尚未验证。', 'units': [{'id': 'U1'}]}
        text = '生产环境尚未验证。'
        gen = {'cond': 'candidate', 'text': text, 'text_hash': screen.rewrite.digest(text), 'reader': '工程师'}
        fidelity = {'units': [{'id':'U1', 'status':'kept', 'quote':text}], 'unlisted':[], 'additions':[]}
        label = 'A' if int(gen['text_hash'][0], 16) % 2 else 'B'
        quality = dict(clarity='same', naturalness='same', concision=label, structure='same', preferred=label, gain='clear', note='重复只说一遍', a_quote=text, b_quote=text)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(screen.rewrite, 'manifest', return_value={'hash':'fixed'}), patch.object(screen.rewrite, 'drafts', return_value=[('sample',case,gen)]), patch.object(screen.rewrite.engine, 'call', side_effect=[(json.dumps(fidelity),{}),(json.dumps(quality),{})]) as model:
                self.assertEqual(screen.screen(directory)[0]['status'], 'ready_for_primary_fidelity')
                self.assertEqual(model.call_count, 2)
                self.assertEqual(screen.screen(directory)[0]['status'], 'ready_for_primary_fidelity')
                self.assertEqual(model.call_count, 2)
                cache = Path(directory)/screen.VERSION/'sample.json'
                value = screen.rewrite.engine.load(cache)
                value['quality']['b_quote']='没有出现在原文里的话'
                screen.rewrite.engine.save(cache,value)
                with self.assertRaises(SystemExit):
                    screen.screen(directory)
                self.assertFalse(screen.rewrite.engine.load(Path(directory)/screen.VERSION/'summary.json')['complete'])
                value['fidelity']['units'][0].update(status='missing',quote='')
                value.pop('quality')
                screen.rewrite.engine.save(cache,value)
                self.assertEqual(screen.screen(directory)[0]['status'], 'rejected_information_changes')
                self.assertEqual(model.call_count, 2)

    def test_quality_requires_literal_nonempty_evidence(self):
        value = dict(clarity='same', naturalness='same', concision='B', structure='same', preferred='B', gain='clear', note='具体收益', a_quote='尚未验证', b_quote='尚未验证')
        screen.validate_quality(value, '生产尚未验证。', '生产尚未验证。')
        value['b_quote'] = '生产已经验证'
        with self.assertRaises(ValueError):
            screen.validate_quality(value, '生产尚未验证。', '生产尚未验证。')
        value['b_quote'] = ''
        with self.assertRaises(ValueError):
            screen.validate_quality(value, '生产尚未验证。', '生产尚未验证。')

    def test_markdown_scaffolding_cannot_create_compression_gain(self):
        original = '## 结果\n\n| 组 | 结论 |\n|---|---|\n| A | **尚未验证** |'
        plain = '结果\n\n组 结论\nA 尚未验证'
        self.assertEqual(screen.readable_chars(original), screen.readable_chars(plain))

    def test_lower_readability_rejects_a_shorter_preferred_candidate(self):
        value = {'clarity': 'A', 'naturalness': 'B', 'concision': 'B', 'structure':'same', 'preferred': 'B', 'gain':'clear'}
        self.assertFalse(screen.passes_quality(value, 'B'))
        value['clarity'] = 'same'
        self.assertTrue(screen.passes_quality(value, 'B'))
        value['naturalness'] = 'A'
        self.assertFalse(screen.passes_quality(value, 'B'))

    def test_clarity_gain_can_pass_without_fixed_compression_but_minor_edits_cannot(self):
        value = dict(clarity='B', naturalness='same', concision='same', structure='same', preferred='B', gain='clear')
        self.assertTrue(screen.passes_quality(value, 'B'))
        value['gain']='minor'
        self.assertFalse(screen.passes_quality(value, 'B'))
        value.update(gain='clear', clarity='same')
        self.assertFalse(screen.passes_quality(value, 'B'))

    def test_all_information_change_categories_block_promotion(self):
        value = {'units': [{'status': 'kept'}], 'unlisted': [], 'additions': []}
        self.assertEqual(screen.information_changes(value), 0)
        value['units'][0]['status'] = 'distorted'
        value['unlisted'].append({'status': 'missing'})
        value['additions'].append({'quote': '新建议'})
        self.assertEqual(screen.information_changes(value), 3)

    def test_structural_regression_blocks_a_shorter_preferred_candidate(self):
        original = '1. 首先检验配置。\n2. 然后发起请求。'
        text = '- 检验配置后发起请求。'
        self.assertLess(screen.readable_chars(text), screen.readable_chars(original))
        case = {'text': original, 'units': [{'id': 'U1'}]}
        draft = dict(cond='candidate', text=text, text_hash=screen.rewrite.digest(text), reader='工程师')
        candidate = 'A' if int(draft['text_hash'][0], 16) % 2 else 'B'
        other = 'B' if candidate == 'A' else 'A'
        fidelity = dict(units=[dict(id='U1', status='kept', quote=text)], unlisted=[], additions=[])
        quality = dict(clarity=candidate, naturalness=candidate, concision=candidate,
                       structure=other, preferred=candidate, gain='clear',
                       note='步骤列表被压成句子，不能单独定位每一步。',
                       a_quote=text if candidate == 'A' else original,
                       b_quote=original if candidate == 'A' else text)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(screen.rewrite, 'manifest', return_value={'hash': 'fixed'}), \
                    patch.object(screen.rewrite, 'drafts', return_value=[('sample', case, draft)]), \
                    patch.object(screen.rewrite.engine, 'call', side_effect=[(json.dumps(fidelity), {}), (json.dumps(quality), {})]):
                self.assertEqual(screen.screen(directory)[0]['status'], 'rejected_editorial_quality')

    def test_quality_rejects_missing_or_invalid_structure_rating(self):
        value = dict(clarity='same', naturalness='same', concision='B', preferred='B',
                     gain='clear', note='说明结构', a_quote='尚未验证', b_quote='尚未验证')
        with self.assertRaises(KeyError):
            screen.validate_quality(value, '尚未验证', '尚未验证')
        value['structure'] = 'more-lists'
        with self.assertRaises(ValueError):
            screen.validate_quality(value, '尚未验证', '尚未验证')

    def test_removing_all_lists_is_rejected_without_model_checks(self):
        for original in ['- 首先检验配置。\n- 然后发起请求。', '1. 首先检验配置。\n2. 然后发起请求。']:
            case = {'text': original}
            text = '检验配置后发起请求。'
            draft = dict(cond='candidate', text=text, text_hash=screen.rewrite.digest(text))
            with self.subTest(original=original), tempfile.TemporaryDirectory() as directory:
                with patch.object(screen.rewrite, 'manifest', return_value={'hash': 'fixed'}), \
                        patch.object(screen.rewrite, 'drafts', return_value=[('sample', case, draft)]), \
                        patch.object(screen.rewrite.engine, 'call') as model:
                    self.assertEqual(screen.screen(directory)[0]['status'], 'rejected_list_structure')
                    model.assert_not_called()


if __name__ == '__main__':
    unittest.main()
