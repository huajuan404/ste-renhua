import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import combine_editor_reviews as combined
import screen_rewrite as screen
import test_editor_review


class CombinedReviewTests(unittest.TestCase):
    def test_collection_preserves_source_hashes_and_filters_before_combining(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            src = root / 'source'
            manifest, drafts, _ = test_editor_review.EditorReviewTests().screened_fixtures(src)
            with patch.object(combined.rewrite, 'manifest', return_value=manifest), \
                    patch.object(combined.rewrite, 'drafts', return_value=drafts):
                path = combined.build([src], root / 'review')
            data = json.loads(path.with_name('editor-review-data.json').read_text())
            self.assertEqual(len(data['variants']), 1)
            self.assertEqual(data['qualification']['total_candidates'], 3)
            self.assertEqual(data['variants'][0]['source_manifest_hash'], 'frozen')
            self.assertEqual(data['manifest_kind'], 'review_collection')
            self.assertEqual(data['manifest_hash'], combined.rewrite.digest(data['source_reviews']))
            digest = data.pop('review_data_hash')
            self.assertEqual(digest, combined.rewrite.digest(data))
            self.assertNotIn('建议先缓一缓上线。', path.read_text())
            self.assertNotIn('__ARTICLES__', path.read_text())

    def test_cross_batch_id_collision_never_creates_a_combined_page(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = [root / 'a', root / 'b']
            fixtures = [test_editor_review.EditorReviewTests().screened_fixtures(src) for src in sources]
            with patch.object(combined.rewrite, 'manifest', return_value=fixtures[0][0]), \
                    patch.object(combined.rewrite, 'drafts', return_value=fixtures[0][1]):
                with self.assertRaisesRegex(ValueError, 'ID 重复'):
                    combined.build(sources, root / 'review')
            self.assertFalse((root / 'review/editor-review.html').exists())

    def test_incomplete_batch_cannot_be_hidden_by_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            src = root / 'source'
            manifest, drafts, summary = test_editor_review.EditorReviewTests().screened_fixtures(src)
            summary['complete'] = False
            combined.rewrite.engine.save(src / screen.VERSION / 'summary.json', summary)
            with patch.object(combined.rewrite, 'manifest', return_value=manifest), \
                    patch.object(combined.rewrite, 'drafts', return_value=drafts):
                with self.assertRaises(ValueError):
                    combined.build([src], root / 'review')
            self.assertFalse((root / 'review/editor-review.html').exists())

    def test_fully_rejected_batch_is_counted_without_entering_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = [root / 'a', root / 'b']
            fixtures = [test_editor_review.EditorReviewTests().screened_fixtures(src) for src in sources]
            judgment_path = sources[1] / 'rewrite-v1/test__edit__r1__opus.json'
            judgment = combined.rewrite.engine.load(judgment_path)
            judgment['units'][0]['status'] = 'distorted'
            combined.rewrite.engine.save(judgment_path, judgment)
            with patch.object(combined.rewrite, 'manifest', return_value=fixtures[0][0]), \
                    patch.object(combined.rewrite, 'drafts', return_value=fixtures[0][1]):
                path = combined.build(sources, root / 'review')
            data = json.loads(path.with_name('editor-review-data.json').read_text())
            self.assertEqual(data['qualification'], {'total_candidates': 6, 'qualified_candidates': 1})
            self.assertIsNone(data['source_reviews'][1]['review_data_hash'])
            self.assertIn('共试 6 篇', path.read_text())

    def test_new_pass_does_not_erase_an_older_information_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            src = root / 'source'
            manifest, drafts, _ = test_editor_review.EditorReviewTests().screened_fixtures(src)
            old_rules = {**screen.screen_rules(), 'version': 'screen-v4', 'renderer_hash': 'older-renderer',
                         'fidelity_prompt': combined.rewrite.JUDGE_PROMPT}
            old_policy = {'manifest_hash': manifest['hash'], 'rules': old_rules, 'rules_hash': combined.rewrite.digest(old_rules)}
            old_result = combined.rewrite.engine.load(src / screen.VERSION / 'test__edit__r1.json')
            old_result['rules_hash'] = old_policy['rules_hash']
            old_result['fidelity']['units'][0]['status'] = 'distorted'
            combined.rewrite.engine.save(src / 'screen-v4/policy.json', old_policy)
            combined.rewrite.engine.save(src / 'screen-v4/test__edit__r1.json', old_result)
            with patch.object(combined.rewrite, 'manifest', return_value=manifest), \
                    patch.object(combined.rewrite, 'drafts', return_value=drafts):
                with self.assertRaisesRegex(ValueError, '没有合格候选'):
                    combined.build([src], root / 'review')
            self.assertFalse((root / 'review/editor-review.html').exists())


if __name__ == '__main__':
    unittest.main()
