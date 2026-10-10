import json
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

import render_review


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.script = False
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.script = True

    def handle_endtag(self, tag):
        if tag == 'script':
            self.script = False

    def handle_data(self, data):
        if not self.script:
            self.text.append(data)


class ReviewTests(unittest.TestCase):
    def test_page_contains_readable_evidence_without_running_scripts(self):
        original = '建议暂缓上线。生产尚未验证。'
        draft = '立即上线。<script>bad()</script>'
        case = {'id': 'case', 'text': original, 'units': [
            {'id': 'U1', 'text': '建议暂缓上线。', 'quote': '建议暂缓上线。'}]}
        manifest = {'hash': 'frozen', 'cases': [case], 'judges': ['opus']}
        gen = {'case': 'case', 'cond': 'none', 'run': 1, 'text': draft, 'text_hash': 'draft'}
        result = {'manifest_hash': 'frozen', 'text_hash': 'draft', 'units': [
            {'id': 'U1', 'status': 'distorted', 'quote': '立即上线。', 'note': '建议被改成命令。'}],
            'unlisted': [], 'additions': []}
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(render_review.rewrite, 'manifest', return_value=manifest), \
                    patch.object(render_review.rewrite, 'drafts', return_value=[('case__none__r1', case, gen)]), \
                    patch.object(render_review.rewrite.engine, 'load', return_value=result):
                render_review.build(directory, directory)
            page = (Path(directory) / 'rewrite-adjudication.html').read_text()
            parsed = VisibleText()
            parsed.feed(page)
            visible = ''.join(parsed.text)
            for content in ['D01', original, '立即上线。', '建议被改成命令。']:
                self.assertIn(content, visible)
            self.assertTrue(page.startswith('<!doctype html>'))
            self.assertNotIn('<script>bad()</script>', page)
            self.assertIn('&lt;script&gt;bad()&lt;/script&gt;', page)
            data = json.loads((Path(directory) / 'review-data.json').read_text())
            saved_hash = data.pop('review_data_hash')
            self.assertEqual(saved_hash, render_review.rewrite.digest(data))


if __name__ == '__main__':
    unittest.main()
