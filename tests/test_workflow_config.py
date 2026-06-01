from __future__ import annotations

from pathlib import Path
import unittest


class WorkflowConfigTests(unittest.TestCase):
    def test_project_metrics_second_project_is_disabled_by_default(self) -> None:
        workflow_path = Path(__file__).resolve().parents[1] / ".github/workflows/roblox_rank_sync.yml"
        workflow_content = workflow_path.read_text(encoding="utf-8")

        self.assertIn(
            "ROBLOX_PROJECT_METRICS_DISABLE_SECOND_PROJECT: ${{ vars.ROBLOX_PROJECT_METRICS_DISABLE_SECOND_PROJECT || 'true' }}",
            workflow_content,
        )
        self.assertNotIn(
            "ROBLOX_PROJECT_METRICS_DISABLE_SECOND_PROJECT: ${{ vars.ROBLOX_PROJECT_METRICS_DISABLE_SECOND_PROJECT || 'false' }}",
            workflow_content,
        )


if __name__ == "__main__":
    unittest.main()
