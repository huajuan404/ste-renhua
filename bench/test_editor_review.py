import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import render_editor_review as review
import screen_rewrite as screen


class EditorReviewTests(unittest.TestCase):
    def fixtures(self):
        case = {'id': 'test', 'text': '建议暂缓上线。', 'units': [
            {'id': 'U1', 'text': '建议暂缓上线。', 'quote': '建议暂缓上线。'}]}
        gen = {'case': 'test', 'cond': 'edit', 'run': 1, 'text': case['text'],
               'text_hash': 'text-hash', 'meta': {'models': ['test-model']}}
        manifest = {'hash': 'frozen', 'cases': [case], 'judges': ['opus'],
                    'conditions': [{'id': 'edit', 'label': '候选 A'}]}
        judgment = {'manifest_hash': 'frozen', 'text_hash': 'text-hash',
                    'units': [{'id': 'U1', 'status': 'kept', 'quote': case['text']}],
                    'additions': [], 'unlisted': []}
        return case, gen, manifest, judgment

    def test_zero_flags_and_unchanged_output_remain_reviewable_without_javascript(self):
        case, gen, manifest, judgment = self.fixtures()
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(review.rewrite, 'manifest', return_value=manifest), \
                    patch.object(review.rewrite, 'drafts', return_value=[('test__edit__r1', case, gen)]), \
                    patch.object(review.rewrite.engine, 'load', return_value=judgment):
                path = review.build(directory, directory)
            page = path.read_text().split('<script')[0]
            self.assertEqual(page.count('建议暂缓上线。'), 4)  # 两侧可读正文及两份逐字文本
            self.assertIn('逐字未改，没有编辑收益', page)
            self.assertIn('不代表已通过人工验收', page)
            self.assertNotIn('__ARTICLES__', page)
            data = json.loads((Path(directory) / 'editor-review-data.json').read_text())
            digest = data.pop('review_data_hash')
            self.assertEqual(digest, review.rewrite.digest(data))

    def test_stale_judgment_is_rejected_before_rendering(self):
        case, gen, manifest, judgment = self.fixtures()
        judgment['text_hash'] = 'another-draft'
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(review.rewrite, 'manifest', return_value=manifest), \
                    patch.object(review.rewrite, 'drafts', return_value=[('test__edit__r1', case, gen)]), \
                    patch.object(review.rewrite.engine, 'load', return_value=judgment):
                with self.assertRaisesRegex(ValueError, '判分与冻结成稿不一致'):
                    review.build(directory, directory)
            self.assertFalse((Path(directory) / 'editor-review.html').exists())

    def test_section_scope_is_visible_and_bound_to_export_hash(self):
        case, gen, manifest, judgment = self.fixtures()
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(review.rewrite, 'manifest', return_value=manifest), patch.object(review.rewrite, 'drafts', return_value=[('test__edit__r1',case,gen)]), patch.object(review.rewrite.engine,'load',return_value=judgment):
                path = review.build(directory,directory,scope='section')
            self.assertIn('不代表整篇文章效果',path.read_text())
            self.assertIn('原稿与改写片段对照',path.read_text())
            self.assertNotIn('__SCOPE',path.read_text())
            data=json.loads((Path(directory)/'editor-review-data.json').read_text())
            digest=data.pop('review_data_hash')
            self.assertEqual(data['scope'],'section')
            self.assertEqual(digest,review.rewrite.digest(data))
            data['scope']='full'
            self.assertNotEqual(digest,review.rewrite.digest(data))

    def test_literal_template_markers_in_source_are_preserved(self):
        case, gen, manifest, judgment = self.fixtures()
        literal = '建议暂缓上线。 __SCOPE__ __SCOPE_NOTE__ __DATA__'
        case['text'] = gen['text'] = literal
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(review.rewrite, 'manifest', return_value=manifest), \
                    patch.object(review.rewrite, 'drafts', return_value=[('test__edit__r1', case, gen)]), \
                    patch.object(review.rewrite.engine, 'load', return_value=judgment):
                page = review.build(directory, directory, scope='section').read_text()
            payload = page.split('<script id="review-data" type="application/json">')[1].split('</script>')[0]
            variant = json.loads(payload)['variants'][0]
            self.assertEqual(variant['original'], literal)
            self.assertEqual(variant['text'], literal)
            self.assertIn(literal, page.split('<script')[0])

    def test_markdown_tables_lists_emphasis_and_untrusted_html(self):
        text = '## 结果\n\n| 组 | 数量 |\n|---|---|\n| A | **2** |\n\n- 约 5%\n- 尚未验证\n\n<script>bad()</script> `x<y`'
        html = review.markdown(text, '')
        for expected in ['<table>', '<strong>2</strong>', '<ul>', '约 5%', '尚未验证',
                         '&lt;script&gt;bad()&lt;/script&gt;', '<code>x&lt;y</code>']:
            self.assertIn(expected, html)
        self.assertNotIn('<script>', html)

    def test_added_paragraphs_are_marked_but_unchanged_facts_are_not(self):
        html = review.markdown('保留条件。\n\n新说法。', '保留条件。')
        self.assertIn('<p>保留条件。</p>', html)
        self.assertIn('<p class="edited">新说法。</p>', html)

    def screened_fixtures(self, directory):
        case, gen, manifest, _ = self.fixtures()
        case['text'] *= 2
        case['title'] = '01 · 上线建议'
        case['provenance'] = {'scope': 'section'}
        manifest['runs'] = 3
        drafts, rows = [], []
        rules = screen.screen_rules()
        stamp = {'manifest_hash': manifest['hash'], 'rules_hash': review.rewrite.digest(rules), 'rules': rules}
        root = Path(directory) / screen.VERSION
        for i, text in enumerate(['建议暂缓上线。', '建议暂缓。', '建议先缓一缓上线。'], 1):
            stem = f'test__edit__r{i}'
            g = {**gen, 'run': i, 'text': text, 'text_hash': review.rewrite.digest(text)}
            drafts.append((stem, case, g))
            rows.append({'id': stem, 'manifest_hash': manifest['hash'], 'text_hash': g['text_hash'],
                         'status': 'ready_for_primary_fidelity' if i < 3 else 'rejected_editorial_quality'})
            if i == 3:  # 不为筛掉的稿件伪造主判分，渲染器不应读取它。
                continue
            label = 'A' if int(g['text_hash'][0], 16) % 2 else 'B'
            quality = {k: label for k in ['clarity', 'naturalness', 'concision', 'preferred']}
            quality.update(structure='same', logic='same', early_answer='same', locating=label,
                           gain='clear', note='合并完整重复，信息集中可定位，原稿没有列表。',
                           a_quote=text if label == 'A' else case['text'],
                           b_quote=case['text'] if label == 'A' else text)
            fidelity = {'units': [{'id': 'U1', 'status': 'kept', 'quote': text}], 'unlisted': [], 'additions': []}
            review.rewrite.engine.save(root / (stem + '.json'),
                                       {**stamp, 'text_hash': g['text_hash'], 'candidate_label': label,
                                        'fidelity': fidelity, 'quality': quality})
            judgment = {**fidelity, 'manifest_hash': manifest['hash'], 'text_hash': g['text_hash']}
            if i == 2:
                judgment['units'] = [{'id': 'U1', 'status': 'distorted', 'quote': text, 'note': '丢掉上线范围。'}]
            review.rewrite.engine.save(Path(directory) / review.rewrite.VERSION / (stem + '__opus.json'), judgment)
        summary = {**stamp, 'complete': True, 'rows': rows}
        review.rewrite.engine.save(root / 'policy.json', stamp)
        review.rewrite.engine.save(root / 'summary.json', summary)
        return manifest, drafts, summary

    def test_qualified_review_filters_small_gains_and_primary_fidelity_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, drafts, _ = self.screened_fixtures(directory)
            with patch.object(review.rewrite, 'manifest', return_value=manifest), \
                    patch.object(review.rewrite, 'drafts', return_value=drafts):
                path = review.build(directory, directory, scope='mixed', qualified_only=True)
            data = json.loads((Path(directory) / 'editor-review-data.json').read_text())
            self.assertEqual([v['id'] for v in data['variants']], ['test__edit__r1'])
            self.assertEqual(data['qualification']['total_candidates'], 3)
            self.assertEqual(data['variants'][0]['scope'], 'section')
            self.assertIn('连续小节', path.read_text())
            self.assertNotIn('建议先缓一缓上线。', path.read_text())
            self.assertNotIn('丢掉上线范围。', path.read_text())
            digest = data.pop('review_data_hash')
            self.assertEqual(digest, review.rewrite.digest(data))
            data['qualification']['total_candidates'] = 2
            self.assertNotEqual(digest, review.rewrite.digest(data))

    def test_incomplete_or_stale_screen_cannot_create_a_review(self):
        for damage in ['incomplete', 'stale_text', 'missing_row']:
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as directory:
                manifest, drafts, summary = self.screened_fixtures(directory)
                if damage == 'incomplete':
                    summary['complete'] = False
                elif damage == 'stale_text':
                    summary['rows'][0]['text_hash'] = 'stale'
                else:
                    summary['rows'].pop()
                review.rewrite.engine.save(Path(directory) / screen.VERSION / 'summary.json', summary)
                with patch.object(review.rewrite, 'manifest', return_value=manifest), \
                        patch.object(review.rewrite, 'drafts', return_value=drafts):
                    with self.assertRaises(ValueError):
                        review.build(directory, directory, qualified_only=True)
                self.assertFalse((Path(directory) / 'editor-review.html').exists())

    def test_ready_status_cannot_override_a_minor_gain(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, drafts, _ = self.screened_fixtures(directory)
            result_path = Path(directory) / screen.VERSION / 'test__edit__r1.json'
            result = review.rewrite.engine.load(result_path)
            result['quality']['gain'] = 'minor'
            review.rewrite.engine.save(result_path, result)
            with patch.object(review.rewrite, 'manifest', return_value=manifest), \
                    patch.object(review.rewrite, 'drafts', return_value=drafts):
                with self.assertRaisesRegex(ValueError, '状态与核对依据不一致'):
                    review.build(directory, directory, qualified_only=True)
            self.assertFalse((Path(directory) / 'editor-review.html').exists())

    def test_ready_status_cannot_override_only_local_expression_gains(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, drafts, _ = self.screened_fixtures(directory)
            result_path = Path(directory) / screen.VERSION / 'test__edit__r1.json'
            result = review.rewrite.engine.load(result_path)
            result['quality'].update(logic='same', early_answer='same', locating='same')
            review.rewrite.engine.save(result_path, result)
            with patch.object(review.rewrite, 'manifest', return_value=manifest), \
                    patch.object(review.rewrite, 'drafts', return_value=drafts):
                with self.assertRaisesRegex(ValueError, '状态与核对依据不一致'):
                    review.build(directory, directory, qualified_only=True)
            self.assertFalse((Path(directory) / 'editor-review.html').exists())

    def test_review_rechecks_growth_instead_of_trusting_ready_status(self):
        for candidate_length in [101, 103]:
            with self.subTest(candidate_length=candidate_length), tempfile.TemporaryDirectory() as directory:
                manifest, drafts, _ = self.screened_fixtures(directory)
                original = drafts[0][1]['text']
                with patch.object(review.rewrite, 'manifest', return_value=manifest), \
                        patch.object(review.rewrite, 'drafts', return_value=drafts), \
                        patch.object(screen, 'readable_chars', side_effect=lambda text: 100 if text == original else candidate_length):
                    if candidate_length == 101:
                        path = review.build(directory, directory, qualified_only=True)
                        self.assertTrue(path.exists())
                    else:
                        with self.assertRaisesRegex(ValueError, '状态与核对依据不一致'):
                            review.build(directory, directory, qualified_only=True)
                        self.assertFalse((Path(directory) / 'editor-review.html').exists())

    def test_fenced_code_keeps_newlines_and_does_not_become_a_list(self):
        text = '```yaml\nnameserver-policy:\n  - https://8.8.8.8/dns-query\n  <script>bad()</script>\n```\n\n- 真实列表'
        html = review.markdown(text, text)
        self.assertIn('<pre><code>nameserver-policy:\n  - https://8.8.8.8/dns-query', html)
        self.assertIn('&lt;script&gt;bad()&lt;/script&gt;', html)
        self.assertEqual(html.count('<ul>'), 1)
        self.assertNotIn('<script>', html)

    def test_nested_lists_and_blank_lines_keep_numbering_and_hierarchy(self):
        text = '1. 第一项\n\n2. 第二项\n   - 子项 A\n   - 子项 B\n\n3. 第三项\n\n- 两个问题\n  1. 问题一\n  2. 问题二\n\n  回到父项的说明。\n\n正文继续。'
        html = review.markdown(text, text)
        self.assertIn('<ol><li value="1">第一项</li><li value="2">第二项<ul>', html)
        self.assertIn('子项 B</li></ul></li><li value="3">第三项</li></ol>', html)
        self.assertIn('问题二</li></ol><p>回到父项的说明。</p></li></ul>', html)
        self.assertTrue(html.endswith('<p>正文继续。</p>'))

    def test_code_fence_after_paragraph_without_blank_line_remains_code(self):
        html = review.markdown('配置如下：\n```yaml\n  - x<y\n```', '')
        self.assertIn('<pre class="edited"><code>  - x&lt;y</code></pre>', html)
        self.assertEqual(html.count('<ul>'), 0)


if __name__ == '__main__':
    unittest.main()
