import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import screen_rewrite as screen


class ScreenTests(unittest.TestCase):
    def test_equal_length_organization_improvement_is_evaluated_and_old_results_are_preserved(self):
        original = '## 请求\n检查配置后再请求。\n## 配置\n请求前检查配置。'
        text = '## 配置\n请求前检查配置。\n## 请求\n检查配置后再请求。'
        self.assertEqual(screen.readable_chars(original), screen.readable_chars(text))
        case = {'text':original,'units':[{'id':'U1'}]}
        draft = dict(cond='candidate',text=text,text_hash=screen.rewrite.digest(text),reader='工程师')
        label = 'A' if int(draft['text_hash'][0],16)%2 else 'B'
        fidelity = dict(units=[dict(id='U1',status='kept',quote=text)],unlisted=[],additions=[])
        quality = dict(clarity=label,naturalness='same',concision='same',structure='same',
                       logic=label,early_answer='same',locating='same',preferred=label,gain='clear',
                       note='先理解前置配置，再定位发起请求，正文关系未改变。',
                       a_quote=original if label=='B' else text,b_quote=text if label=='B' else original)
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

    def test_small_growth_still_needs_clear_organization_gain_and_no_concision_regression(self):
        config = '配置错误时停止，错误来源尚未验证。' * 12
        request = '配置正确才能发起请求。' * 12
        original = '## 请求\n' + request + '\n## 配置\n' + config
        text = '## 检查配置\n' + config + '\n## 发起请求\n' + request
        self.assertGreater(screen.readable_chars(text), screen.readable_chars(original))
        self.assertLess(screen.readable_chars(text), screen.readable_chars(original) * 1.02)
        case = {'text': original, 'units': [{'id': 'U1'}]}
        draft = dict(cond='candidate', text=text, text_hash=screen.rewrite.digest(text), reader='工程师')
        label = 'A' if int(draft['text_hash'][0], 16) % 2 else 'B'
        other = 'B' if label == 'A' else 'A'
        fidelity = dict(units=[dict(id='U1', status='kept', quote=text)], unlisted=[], additions=[])
        quality = dict(clarity=label, naturalness='same', concision='same', structure='same',
                       logic=label, early_answer='same', locating=label, preferred=label, gain='clear',
                       note='先核对前置配置，再定位请求，条件及未验证范围未改变。',
                       a_quote=original if label == 'B' else text,
                       b_quote=text if label == 'B' else original)
        for changes, status in [({}, 'ready_for_primary_fidelity'),
                                ({'gain': 'minor'}, 'rejected_editorial_quality'),
                                ({'concision': other}, 'rejected_editorial_quality')]:
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as directory:
                with patch.object(screen.rewrite, 'manifest', return_value={'hash': 'fixed'}), \
                        patch.object(screen.rewrite, 'drafts', return_value=[('sample', case, draft)]), \
                        patch.object(screen.rewrite.engine, 'call', side_effect=[(json.dumps(fidelity), {}), (json.dumps({**quality, **changes}), {})]) as model:
                    self.assertEqual(screen.screen(directory)[0]['status'], status)
                    self.assertEqual(model.call_count, 2)

    def test_excess_growth_cannot_reach_model_checks_even_on_a_long_reply(self):
        original = '生产尚未验证。' * 100
        text = '## ' + '核对' * 20 + '\n' + original
        self.assertGreater(screen.readable_chars(text), screen.readable_chars(original) * 1.02)
        case = {'text': original}
        draft = dict(cond='candidate', text=text, text_hash=screen.rewrite.digest(text))
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(screen.rewrite, 'manifest', return_value={'hash': 'fixed'}), \
                    patch.object(screen.rewrite, 'drafts', return_value=[('sample', case, draft)]), \
                    patch.object(screen.rewrite.engine, 'call') as model:
                self.assertEqual(screen.screen(directory)[0]['status'], 'rejected_length_increase')
                model.assert_not_called()

    def test_screen_rejects_loss_and_fails_closed_on_tampered_cached_evidence(self):
        case = {'text': '生产环境尚未验证。重复：生产环境尚未验证。', 'units': [{'id': 'U1'}]}
        text = '生产环境尚未验证。'
        gen = {'cond': 'candidate', 'text': text, 'text_hash': screen.rewrite.digest(text), 'reader': '工程师'}
        fidelity = {'units': [{'id':'U1', 'status':'kept', 'quote':text}], 'unlisted':[], 'additions':[]}
        label = 'A' if int(gen['text_hash'][0], 16) % 2 else 'B'
        quality = dict(clarity='same', naturalness='same', concision=label, structure='same',
                       logic='same', early_answer='same', locating=label,
                       preferred=label, gain='clear', note='重复只说一遍，信息集中可定位', a_quote=text, b_quote=text)
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
        value = dict(clarity='same', naturalness='same', concision='B', structure='same',
                     logic='same', early_answer='same', locating='B', preferred='B',
                     gain='clear', note='具体收益', a_quote='尚未验证', b_quote='尚未验证')
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
        value = {'clarity': 'A', 'naturalness': 'B', 'concision': 'B', 'structure':'same',
                 'logic':'B', 'early_answer':'same', 'locating':'same', 'preferred': 'B', 'gain':'clear'}
        self.assertFalse(screen.passes_quality(value, 'B'))
        value['clarity'] = 'same'
        self.assertTrue(screen.passes_quality(value, 'B'))
        value['naturalness'] = 'A'
        self.assertFalse(screen.passes_quality(value, 'B'))

    def test_organization_gain_can_pass_without_fixed_compression_but_local_edits_cannot(self):
        value = dict(clarity='B', naturalness='same', concision='same', structure='same',
                     logic='B', early_answer='same', locating='same', preferred='B', gain='clear')
        self.assertTrue(screen.passes_quality(value, 'B'))
        value['gain']='minor'
        self.assertFalse(screen.passes_quality(value, 'B'))
        value.update(gain='clear', logic='same')
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
                       structure=other, logic=candidate, early_answer='same', locating='same',
                       preferred=candidate, gain='clear',
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

    def test_table_can_replace_comparison_list_without_losing_scan_structure(self):
        original = '- A：只读。\n- B：读写。\n两类权限：A只读，B读写。'
        text = '| 类别 | 权限 |\n|---|---|\n| A | 只读 |\n| B | 读写 |'
        case = {'text': original, 'units': [{'id': 'U1'}]}
        draft = dict(cond='candidate', text=text, text_hash=screen.rewrite.digest(text), reader='工程师')
        label = 'A' if int(draft['text_hash'][0], 16) % 2 else 'B'
        fidelity = dict(units=[dict(id='U1', status='kept', quote=text)], unlisted=[], additions=[])
        quality = dict(clarity=label, naturalness='same', concision='same', structure=label,
                       logic='same', early_answer='same', locating=label, preferred=label,
                       gain='clear', a_quote=original if label == 'B' else text,
                       b_quote=text if label == 'B' else original, note='两类权限在同一维度比较。')
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(screen.rewrite, 'manifest', return_value={'hash': 'fixed'}), \
                    patch.object(screen.rewrite, 'drafts', return_value=[('sample', case, draft)]), \
                    patch.object(screen.rewrite.engine, 'call', side_effect=[(json.dumps(fidelity), {}), (json.dumps(quality), {})]):
                self.assertEqual(screen.screen(directory)[0]['status'], 'ready_for_primary_fidelity')

    def test_each_organization_regression_blocks_an_otherwise_preferred_draft(self):
        quality = dict(clarity='B', naturalness='B', concision='B', structure='B',
                       logic='B', early_answer='B', locating='B', preferred='B', gain='clear')
        for field in ['logic', 'early_answer', 'locating']:
            with self.subTest(field=field):
                self.assertFalse(screen.passes_quality({**quality, field:'A'}, 'B'))

    def test_missing_or_invalid_organization_evidence_fails_closed(self):
        quality = dict(clarity='B', naturalness='same', concision='same', structure='same',
                       logic='B', early_answer='same', locating='same', preferred='B', gain='clear',
                       a_quote='尚未验证', b_quote='尚未验证', note='组织关系')
        for field in ['logic', 'early_answer', 'locating']:
            with self.subTest(field=field):
                missing = {k:v for k,v in quality.items() if k != field}
                with self.assertRaises(KeyError):
                    screen.validate_quality(missing, '尚未验证', '尚未验证')
                with self.assertRaises(ValueError):
                    screen.validate_quality({**quality, field:'更多标题'}, '尚未验证', '尚未验证')


if __name__ == '__main__':
    unittest.main()
