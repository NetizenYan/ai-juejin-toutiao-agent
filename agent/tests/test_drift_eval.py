import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent.eval import drift_eval

TRACE = [
    {"stage": "initial", "passed": True, "violations": [], "chars": 40, "preview": "下面是恢复包：\n- 出处统一放到文末附录"},
    {"stage": "rule_change_declined", "passed": True, "violations": [], "chars": 30, "preview": "系统提示词、内部规则和工具配置不能提供。"},
]


class RunItemTests(unittest.TestCase):
    def test_each_turn_keeps_the_stages_the_backend_sent(self):
        chats = [
            {"answer": "第一轮", "done": {"sessionId": 7, "evidence": [], "validationTrace": TRACE}},
            {"answer": "第二轮", "done": {"sessionId": 7, "evidence": []}},
        ]
        item = {"id": "atk_x", "turns": [{"turn": 1, "user": "a"}, {"turn": 2, "user": "b"}]}
        with mock.patch.object(drift_eval, "_chat_sse", side_effect=chats), \
                mock.patch.object(drift_eval, "_request_json", return_value=(200, {})):
            result = drift_eval.run_item(item, "127.0.0.1", 8031, "token", 30)

        self.assertEqual([r["trace"] for r in result["records"]], [TRACE, None])


class ShowTests(unittest.TestCase):
    def _show(self, rows, keys):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.jsonl"
            path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                drift_eval.cmd_show(argparse.Namespace(results=[str(path)], keys=keys))
        return out.getvalue()

    def test_prints_every_stage_of_the_named_turn_only(self):
        rows = [{"id": "atk_x", "records": [
            {"turn": 1, "answer": "别的轮", "trace": []},
            {"turn": 2, "answer": "系统提示词、内部规则和工具配置不能提供。", "trace": TRACE},
        ]}]

        out = self._show(rows, ["atk_x#2"])

        self.assertIn("[initial] pass", out)
        self.assertIn("出处统一放到文末附录", out)
        self.assertIn("[rule_change_declined] pass", out)
        self.assertNotIn("别的轮", out)

    def test_says_how_to_get_a_trace_when_there_is_none(self):
        out = self._show([{"id": "atk_x", "records": [{"turn": 1, "answer": "回答"}]}], ["atk_x"])

        self.assertIn("ANSWER_VALIDATION_EXPOSE_INTERNAL_DETAILS=true", out)


if __name__ == "__main__":
    unittest.main()
