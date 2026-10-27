from __future__ import annotations

from pathlib import Path
import unittest


class WorkflowConfigTests(unittest.TestCase):
    def test_primary_project_test_chat_ids_can_be_passed_from_dispatch_inputs(self) -> None:
        workflow_path = Path(__file__).resolve().parents[1] / ".github/workflows/roblox_rank_sync.yml"
        workflow_content = workflow_path.read_text(encoding="utf-8")

        self.assertIn("project_metrics_primary_project_test_chat_ids:", workflow_content)
        self.assertIn(
            "PROJECT_METRICS_PRIMARY_PROJECT_TEST_CHAT_IDS: ${{ github.event.inputs.project_metrics_primary_project_test_chat_ids || vars.PROJECT_METRICS_PRIMARY_PROJECT_TEST_CHAT_IDS || '' }}",
            workflow_content,
        )

    def test_report_mode_choices_exclude_offline_top100_message(self) -> None:
        workflow_path = Path(__file__).resolve().parents[1] / ".github/workflows/roblox_rank_sync.yml"
        workflow_content = workflow_path.read_text(encoding="utf-8")

        self.assertIn("type: choice", workflow_content)
        for report_mode in ("top_trending_sheet", "roblox_project_daily_metrics", "roblox_money"):
            self.assertIn(f"          - {report_mode}", workflow_content)
        self.assertNotIn("          - top100_message", workflow_content)
        self.assertNotIn("'top100_message'", workflow_content)

    def test_removed_project_slots_are_not_injected(self) -> None:
        workflow_path = Path(__file__).resolve().parents[1] / ".github/workflows/roblox_rank_sync.yml"
        workflow_content = workflow_path.read_text(encoding="utf-8")

        for removed in (
            "ROBLOX_CREATOR_OVERVIEW_URL_2",
            "ROBLOX_CREATOR_OVERVIEW_URL_6",
            "ROBLOX_PROJECT_METRICS_DISABLE_SECOND_PROJECT",
            "FEISHU_PROJECT_METRICS_2_",
            "FEISHU_PROJECT_METRICS_6_",
        ):
            self.assertNotIn(removed, workflow_content)

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
