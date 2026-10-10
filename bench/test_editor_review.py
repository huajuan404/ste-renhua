import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import render_editor_review as review


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


if __name__ == '__main__':
    unittest.main()
