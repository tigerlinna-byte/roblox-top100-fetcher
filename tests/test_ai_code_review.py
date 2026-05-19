import unittest

from scripts import ai_code_review


class AiCodeReviewTest(unittest.TestCase):
    """验证 AI 审核脚本中不依赖网络的核心文本处理逻辑。"""

    def test_extract_response_text_prefers_output_text(self) -> None:
        """当 Responses API 返回 output_text 时，应优先使用该字段。"""
        data = {
            "output_text": "  未发现阻塞问题  ",
            "output": [],
        }

        self.assertEqual(ai_code_review.extract_response_text(data), "未发现阻塞问题")

    def test_extract_response_text_reads_nested_content(self) -> None:
        """兼容 Responses API 的 message/content 嵌套文本结构。"""
        data = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "阻塞问题：无"},
                        {"type": "output_text", "text": "建议问题：无"},
                    ],
                }
            ]
        }

        self.assertEqual(
            ai_code_review.extract_response_text(data),
            "阻塞问题：无\n\n建议问题：无",
        )

    def test_build_review_body_contains_push_metadata(self) -> None:
        """审核正文应包含 push 范围信息，供 Summary 和飞书通知复用。"""
        target = ai_code_review.ReviewTarget(
            base_sha="1" * 40,
            head_sha="2" * 40,
            ref_name="main",
            actor="tester",
            repository="owner/repo",
        )

        body = ai_code_review.build_review_body("未发现阻塞问题", "gpt-5.4-mini", target)

        self.assertIn("`1111111`...`2222222`", body)
        self.assertIn("owner/repo", body)
        self.assertIn("未发现阻塞问题", body)
        self.assertIn("gpt-5.4-mini", body)


if __name__ == "__main__":
    unittest.main()
