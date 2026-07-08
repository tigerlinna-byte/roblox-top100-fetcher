from __future__ import annotations

from pathlib import Path
import unittest


class WorkflowConfigTests(unittest.TestCase):
    def test_project_metrics_second_project_is_disabled_by_default(self) -> None:
        workflow_path = Path(__file__).resolve().parents[1] / ".github/workflows/roblox_rank_sync.yml"
        workflow_content = workflow_path.read_text(encoding="utf-8")

        self.assertIn("project_metrics_primary_project_test_chat_ids:", workflow_content)
        self.assertIn(
            "ROBLOX_PROJECT_METRICS_DISABLE_SECOND_PROJECT: ${{ vars.ROBLOX_PROJECT_METRICS_DISABLE_SECOND_PROJECT || 'true' }}",
            workflow_content,
        )
        self.assertIn(
            "PROJECT_METRICS_PRIMARY_PROJECT_TEST_CHAT_IDS: ${{ github.event.inputs.project_metrics_primary_project_test_chat_ids || vars.PROJECT_METRICS_PRIMARY_PROJECT_TEST_CHAT_IDS || '' }}",
            workflow_content,
        )
        self.assertNotIn(
            "ROBLOX_PROJECT_METRICS_DISABLE_SECOND_PROJECT: ${{ vars.ROBLOX_PROJECT_METRICS_DISABLE_SECOND_PROJECT || 'false' }}",
            workflow_content,
        )

    def test_project_metrics_fourth_project_defaults_to_soccer_rng(self) -> None:
        workflow_path = Path(__file__).resolve().parents[1] / ".github/workflows/roblox_rank_sync.yml"
        workflow_content = workflow_path.read_text(encoding="utf-8")

        self.assertIn(
            "ROBLOX_CREATOR_OVERVIEW_URL_4: ${{ vars.ROBLOX_CREATOR_OVERVIEW_URL_4 || 'https://create.roblox.com/dashboard/creations/experiences/10304101434/overview' }}",
            workflow_content,
        )
        self.assertIn(
            "FEISHU_PROJECT_METRICS_4_SPREADSHEET_TITLE: ${{ vars.FEISHU_PROJECT_METRICS_4_SPREADSHEET_TITLE || 'Soccer RNG' }}",
            workflow_content,
        )

    def test_project_metrics_fifth_project_defaults_to_soccer_tycoon(self) -> None:
        workflow_path = Path(__file__).resolve().parents[1] / ".github/workflows/roblox_rank_sync.yml"
        workflow_content = workflow_path.read_text(encoding="utf-8")

        self.assertIn(
            "ROBLOX_CREATOR_OVERVIEW_URL_5: ${{ vars.ROBLOX_CREATOR_OVERVIEW_URL_5 || 'https://create.roblox.com/dashboard/creations/experiences/10403337696/overview' }}",
            workflow_content,
        )
        self.assertIn(
            "FEISHU_PROJECT_METRICS_5_SPREADSHEET_TITLE: ${{ vars.FEISHU_PROJECT_METRICS_5_SPREADSHEET_TITLE || 'soccer大亨版' }}",
            workflow_content,
        )


if __name__ == "__main__":
    unittest.main()
