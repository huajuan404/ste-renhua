"""运行器的失败退出与断点续跑检查，不调用真实模型。"""
import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run
import mutate


class RunnerTests(unittest.TestCase):
    def test_failed_job_does_not_discard_success(self):
        with tempfile.TemporaryDirectory() as d:
            success, failure = Path(d) / "success.json", Path(d) / "failure.json"

            def work(job):
                if job[0] == failure:
                    raise RuntimeError("模拟调用失败")
                run.save(job[0], {"ok": True})

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as exc:
                    run.run_pool(work, [(success,), (failure,)], 2)
            self.assertEqual(exc.exception.code, 1)
            self.assertEqual(run.load(success), {"ok": True})
            self.assertFalse(failure.exists())

    def test_generation_resume_skips_saved_draft(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            conditions = root / "conditions.json"
            conditions.write_text(json.dumps([{"id": "none"}]))
            saved = root / "gen" / "example__none__r1.json"
            run.save(saved, {"text": "原来的成稿"})
            a = argparse.Namespace(out=d, conditions=str(conditions), conds=None,
                                   cases=None, runs=2, workers=1)
            case = {"id": "example", "task": "写回复", "materials": "材料"}
            with patch.object(run, "load_cases", return_value=[case]), patch.object(
                    run, "call", return_value=("新成稿", {"models": ["test"]})) as call:
                run.cmd_gen(a)
            call.assert_called_once()
            self.assertEqual(run.load(saved)["text"], "原来的成稿")
            self.assertEqual(run.load(root / "gen" / "example__none__r2.json")["text"], "新成稿")

    def test_unknown_or_empty_conditions_fail_before_model_call(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "conditions.json"
            for conditions, selection in [([{"id": "none"}], ["typo"]), ([], None)]:
                with self.subTest(conditions=conditions):
                    path.write_text(json.dumps(conditions))
                    a = argparse.Namespace(out=d, conditions=str(path), conds=selection)
                    with patch.object(run, "call") as call, self.assertRaises(SystemExit):
                        run.cmd_gen(a)
                    call.assert_not_called()

    def test_claude_error_reports_reason(self):
        error = {"type": "result", "is_error": True,
                 "result": "You've hit your session limit · resets 4pm", "usage": {}}
        process = argparse.Namespace(stdout=json.dumps([error]), stderr="")
        with patch.object(run.subprocess, "run", return_value=process):
            with self.assertRaisesRegex(RuntimeError, "session limit.*4pm"):
                run.call_claude("haiku", "test")

    def test_explained_code_control_ignores_original_abbreviation(self):
        mutation = {"before": "带大量图片的 PRD 有 6 份",
                    "after": "带大量图片的 PRD（下面叫重图 PRD）有 6 份"}
        kind = mutate.KIND["code-ok"]
        self.assertTrue(mutate.hit_express(kind, mutation, {"hard": [{"quote": "PRD"}]}))
        self.assertFalse(mutate.hit_express(kind, mutation, {"hard": [{"quote": "重图 PRD"}]}))

    def test_judging_without_drafts_fails(self):
        with tempfile.TemporaryDirectory() as d:
            with patch("sys.argv", ["run.py", "judge", "--out", d]), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as exc:
                    run.main()
            self.assertEqual(exc.exception.code, 2)

    def test_invalid_citation_is_retried_before_saving(self):
        for fn, stage in [(run.cmd_judge, run.JUDGE_DIR), (run.cmd_express, run.EXPRESS_DIR)]:
            for bad_quote in ["", "批大小是 5000"]:
                with self.subTest(stage=stage, quote=bad_quote), tempfile.TemporaryDirectory() as d:
                    root = Path(d)
                    run.save(root / "gen" / "example__none__r1.json",
                             {"case": "example", "text": "批大小是 500。"})
                    case = {"id": "example", "materials": "批大小是 500。",
                            "facts": [{"id": "F1", "text": "批大小是 500。"}]}

                    def verdict(quote):
                        return json.dumps({"facts": [{"id": "F1", "status": "kept", "quote": quote}],
                                           "hard": [{"kind": "code", "quote": quote}]}), {}

                    replies = [verdict(bad_quote), verdict("批大小是 500")]
                    with patch.object(run, "load_cases", return_value=[case]), patch.object(
                            run, "JUDGES", ["test"]), patch.object(run.time, "sleep"), patch.object(
                            run, "call", side_effect=replies) as call:
                        fn(argparse.Namespace(out=d, workers=1, judges=None))
                    self.assertEqual(call.call_count, 2)
                    saved = run.load(root / stage / "example__none__r1__test.json")
                    self.assertEqual(saved["facts" if stage == run.JUDGE_DIR else "hard"][0]["quote"],
                                     "批大小是 500")


if __name__ == "__main__":
    unittest.main()
