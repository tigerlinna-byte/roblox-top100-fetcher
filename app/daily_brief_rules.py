"""每日早报的业务规则数据。

本文件只存放阈值、权重与展示规则，供运营/开发直接调整；计算逻辑不在这里。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricChangeThreshold:
    """描述单个指标相对基线的提醒阈值。

    rise_ratio：涨幅达到该比例时提醒，例如 1.0 表示涨到基线的 2 倍；None 表示不看上涨。
    fall_ratio：跌幅达到该比例时提醒，例如 0.5 表示跌到基线的一半；None 表示不看下跌。
    """

    rise_ratio: float | None
    fall_ratio: float | None


# ---------------------------------------------------------------------------
# 自家项目指标提醒
# ---------------------------------------------------------------------------

# 基线窗口：统计日之前的连续天数，取这些天的均值作为对比基线。
PROJECT_TREND_BASELINE_DAYS = 7
# 基线最少有效天数：窗口内有值的天数不足时不做判断，避免新项目或缺数据时误报。
PROJECT_TREND_MIN_BASELINE_DAYS = 4

# 提醒的最低体量：统计日峰值 PCU 与前若干天峰值 PCU 均值都低于该值时，项目指标和收入都不提醒涨跌。
# 体量太小时波动对业务影响小，且小数字天然波动大；冲上或跌破该值的变化仍会提醒。对所有档位生效。
PROJECT_ALERT_MIN_PEAK_CCU = 100

# 观测档位：默认“宽松”只在翻倍或腰斩时提醒；项目达到一定体量后人工改为“标准”。
RELAXED_ALERT_PROFILE = "relaxed"
STANDARD_ALERT_PROFILE = "standard"
DEFAULT_PROJECT_ALERT_PROFILE = RELAXED_ALERT_PROFILE
# 人工标记：需要细看的项目在此登记为标准观测，键为 Roblox 项目 ID。
PROJECT_ALERT_PROFILE_BY_PROJECT_ID: dict[str, str] = {}

# 参与提醒的项目指标及其展示名，顺序即卡片中的展示顺序。
PROJECT_ALERT_METRIC_LABELS: dict[str, str] = {
    "peak_ccu": "峰值PCU",
    "day1_retention": "D1留存",
    "day7_retention": "D7留存",
    "average_session_time": "平均时长",
    "payer_conversion_rate": "付费率",
    "arpdau": "ARPDAU",
    "client_crash_rate": "崩溃率",
}
# 收入提醒使用的指标键与展示名（收入数据来自收入日报，不在项目表格里）。
REVENUE_ALERT_METRIC = "daily_robux"
REVENUE_ALERT_METRIC_LABEL = "日收入"

# 各档位的阈值；崩溃率只关心上涨，因此 fall_ratio 为 None。
PROJECT_ALERT_THRESHOLDS: dict[str, dict[str, MetricChangeThreshold]] = {
    RELAXED_ALERT_PROFILE: {
        "peak_ccu": MetricChangeThreshold(rise_ratio=1.0, fall_ratio=0.5),
        "day1_retention": MetricChangeThreshold(rise_ratio=1.0, fall_ratio=0.5),
        "day7_retention": MetricChangeThreshold(rise_ratio=1.0, fall_ratio=0.5),
        "average_session_time": MetricChangeThreshold(rise_ratio=1.0, fall_ratio=0.5),
        "payer_conversion_rate": MetricChangeThreshold(rise_ratio=1.0, fall_ratio=0.5),
        "arpdau": MetricChangeThreshold(rise_ratio=1.0, fall_ratio=0.5),
        "client_crash_rate": MetricChangeThreshold(rise_ratio=1.0, fall_ratio=None),
        REVENUE_ALERT_METRIC: MetricChangeThreshold(rise_ratio=1.0, fall_ratio=0.5),
    },
    STANDARD_ALERT_PROFILE: {
        "peak_ccu": MetricChangeThreshold(rise_ratio=0.2, fall_ratio=0.2),
        "day1_retention": MetricChangeThreshold(rise_ratio=0.2, fall_ratio=0.2),
        "day7_retention": MetricChangeThreshold(rise_ratio=0.2, fall_ratio=0.2),
        "average_session_time": MetricChangeThreshold(rise_ratio=0.2, fall_ratio=0.2),
        "payer_conversion_rate": MetricChangeThreshold(rise_ratio=0.2, fall_ratio=0.2),
        "arpdau": MetricChangeThreshold(rise_ratio=0.2, fall_ratio=0.2),
        "client_crash_rate": MetricChangeThreshold(rise_ratio=0.5, fall_ratio=None),
        REVENUE_ALERT_METRIC: MetricChangeThreshold(rise_ratio=0.2, fall_ratio=0.2),
    },
}

# 项目没有触发提醒时，卡片里展示的核心数字（字段名 -> 展示名）。
PROJECT_SUMMARY_METRIC_LABELS: dict[str, str] = {
    "peak_ccu": "峰值PCU",
    "day1_retention": "D1",
    "average_session_time": "时长",
}
# 项目名展示时去掉的表格标题后缀，例如“Shoot or Shot 每日数据”只显示“Shoot or Shot”。
PROJECT_TITLE_SUFFIXES_TO_STRIP: tuple[str, ...] = ("每日数据",)

# ---------------------------------------------------------------------------
# 大盘涨跌（在玩榜总 CCU）
# ---------------------------------------------------------------------------

# 大盘使用的榜单：在玩榜按实时在线人数排序，最能代表整体热度。
MARKET_PULSE_SHEET_KEY = "top_playing_now"
# 头部范围：前 N 名合计，容易被个别超大游戏带动。
MARKET_PULSE_HEAD_SIZE = 10
# 大盘范围：前 N 名合计，更能代表整体。
MARKET_PULSE_BROAD_SIZE = 100
# 涨跌判定阈值：相对对比日变化超过该比例才算“明显上涨/下跌”，否则为“平稳”。
MARKET_PULSE_CHANGE_THRESHOLD = 0.10
# 周对比间隔天数：与上周同一天对比，抵消周末效应。
MARKET_PULSE_WEEK_COMPARE_DAYS = 7
# 日对比间隔天数：与昨天对比。
MARKET_PULSE_DAY_COMPARE_DAYS = 1
# 大盘 CCU 历史保留天数，同时控制 GitHub Variable 体积。
MARKET_CCU_HISTORY_KEEP_DAYS = 30

# ---------------------------------------------------------------------------
# 值得关注项目（打分）
# ---------------------------------------------------------------------------

# 只考察各榜单前 N 名，避免收入榜 100 名以后的排名波动制造噪音。
SPOTLIGHT_MAX_CONSIDERED_RANK = 100
# 新游信号：首次上线不超过该天数且已上任一榜单。
SPOTLIGHT_NEW_GAME_MAX_AGE_DAYS = 30
SPOTLIGHT_NEW_GAME_SCORE = 3
# 收入榜新进前 N 信号：本次在收入榜前 N，上次运行不在前 N。
SPOTLIGHT_TOP_EARNING_RANK_LIMIT = 20
SPOTLIGHT_TOP_EARNING_SCORE = 3
# 新上榜信号：最近若干次运行首次出现在某榜单，且首次上线未满 6 个月（沿用今日关注规则）。
SPOTLIGHT_NEW_ENTRY_SCORE = 2
# 排名飙升信号：较上次运行上升达到该名次即得基础分，每多上升一个步长再加分，加分有上限。
SPOTLIGHT_RANK_SURGE_MIN_STEP = 20
SPOTLIGHT_RANK_SURGE_SCORE = 2
SPOTLIGHT_RANK_SURGE_BONUS_PER_STEP = 1
SPOTLIGHT_RANK_SURGE_MAX_BONUS = 3
# 多榜信号：同时出现在多个榜单时，每多一个榜单加分。
SPOTLIGHT_MULTI_SHEET_SCORE_PER_EXTRA = 1
# 卡片最多展示的值得关注项目数（含“今日最突出”）。
SPOTLIGHT_MAX_ENTRIES = 8
# “今日最突出”的最低总分，没有游戏达到时不评选，避免硬凑。
SPOTLIGHT_STANDOUT_MIN_SCORE = 3

# ---------------------------------------------------------------------------
# 品类风向
# ---------------------------------------------------------------------------

# 热门榜前 N 名用于统计主流品类。
GENRE_TRENDING_TOP_SIZE = 20
# 品类至少出现的款数，低于该值不写入风向，避免“1 款也算趋势”。
GENRE_MIN_COUNT = 2
