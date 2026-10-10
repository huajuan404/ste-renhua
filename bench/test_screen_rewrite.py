import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import screen_rewrite as screen


class ScreenTests(unittest.TestCase):
    def test_screen_rejects_loss_and_fails_closed_on_tampered_cached_evidence(self):
        case = {'text': '生产环境尚未验证。重复：生产环境尚未验证。', 'units': [{'id': 'U1'}]}
        text = '生产环境尚未验证。'
        gen = {'cond': 'candidate', 'text': text, 'text_hash': screen.rewrite.digest(text), 'reader': '工程师'}
        fidelity = {'units': [{'id':'U1', 'status':'kept', 'quote':text}], 'unlisted':[], 'additions':[]}
        label = 'A' if int(gen['text_hash'][0], 16) % 2 else 'B'
        quality = dict(clarity='same', naturalness='same', concision=label, preferred=label, a_quote=text, b_quote=text)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(screen.rewrite, 'manifest', return_value={'hash':'fixed'}), patch.object(screen.rewrite, 'drafts', return_value=[('sample',case,gen)]), patch.object(screen.rewrite.engine, 'call', side_effect=[(json.dumps(fidelity),{}),(json.dumps(quality),{})]) as model:
                self.assertEqual(screen.screen(directory)[0]['status'], 'ready_for_primary_fidelity')
                self.assertEqual(model.call_count, 2)
                self.assertEqual(screen.screen(directory)[0]['status'], 'ready_for_primary_fidelity')
                self.assertEqual(model.call_count, 2)
                cache = Path(directory)/'screen-v1/sample.json'
                value = screen.rewrite.engine.load(cache)
                value['quality']['b_quote']='没有出现在原文里的话'
                screen.rewrite.engine.save(cache,value)
                with self.assertRaises(SystemExit):
                    screen.screen(directory)
                self.assertFalse(screen.rewrite.engine.load(Path(directory)/'screen-v1/summary.json')['complete'])
                value['fidelity']['units'][0].update(status='missing',quote='')
                value.pop('quality')
                screen.rewrite.engine.save(cache,value)
                self.assertEqual(screen.screen(directory)[0]['status'], 'rejected_information_changes')
                self.assertEqual(model.call_count, 2)

    def test_quality_requires_literal_nonempty_evidence(self):
        value = dict(clarity='same', naturalness='same', concision='B', preferred='B', a_quote='尚未验证', b_quote='尚未验证')
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
        value = {'clarity': 'A', 'naturalness': 'B', 'concision': 'B', 'preferred': 'B'}
        self.assertFalse(screen.passes_quality(value, 'B'))
        value['clarity'] = 'same'
        self.assertTrue(screen.passes_quality(value, 'B'))
        value['naturalness'] = 'A'
        self.assertFalse(screen.passes_quality(value, 'B'))

    def test_all_information_change_categories_block_promotion(self):
        value = {'units': [{'status': 'kept'}], 'unlisted': [], 'additions': []}
        self.assertEqual(screen.information_changes(value), 0)
        value['units'][0]['status'] = 'distorted'
        value['unlisted'].append({'status': 'missing'})
        value['additions'].append({'quote': '新建议'})
        self.assertEqual(screen.information_changes(value), 3)


if __name__ == '__main__':
    unittest.main()
