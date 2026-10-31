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
# 多榜信号：同时出现在多个榜单时，每多一个榜单加分（只统计各榜前 N 名）。
SPOTLIGHT_MULTI_SHEET_SCORE_PER_EXTRA = 1

# 收入榜比其他榜单稳定得多（前 100 名每天变化中位数只有 2～4 名），单独设置更灵敏的规则。
# 收入榜考察范围：上线不超过该天数的游戏，收入榜看到前 N 名；它们必须有收入榜上升信号才入选。
SPOTLIGHT_EARNING_MAX_CONSIDERED_RANK = 300
SPOTLIGHT_EARNING_DEEP_RANK_MAX_AGE_DAYS = 180
# 收入榜飙升：较上次运行上升达到该名次即得基础分，每多上升一个步长再加分，加分有上限。
SPOTLIGHT_EARNING_SURGE_MIN_STEP = 10
SPOTLIGHT_EARNING_SURGE_SCORE = 3
SPOTLIGHT_EARNING_SURGE_BONUS_PER_STEP = 1
SPOTLIGHT_EARNING_SURGE_MAX_BONUS = 3
# 冲进收入榜前 N：上次运行在前 N 以外（或不在榜），本次进入前 N。
SPOTLIGHT_EARNING_TOP100_RANK_LIMIT = 100
SPOTLIGHT_EARNING_TOP100_SCORE = 3
# 收入榜一周爬升：与已保存历史中最早一次运行（约 7 天前）相比上升达到该名次；当时不在榜按第 N+1 名计。
SPOTLIGHT_EARNING_WEEKLY_CLIMB_MIN_STEP = 50
SPOTLIGHT_EARNING_WEEKLY_CLIMB_SCORE = 2
# 卡片最多展示的值得关注项目数（含“今日最突出”）。
SPOTLIGHT_MAX_ENTRIES = 8
# “今日最突出”的最低总分，没有游戏达到时不评选，避免硬凑。
SPOTLIGHT_STANDOUT_MIN_SCORE = 3

# ---------------------------------------------------------------------------
# 长线潜力（基于每日历史快照）
# ---------------------------------------------------------------------------

# 每日快照的记录范围：各榜单前 N 名中首次上线不超过该天数的游戏，老游戏不需要看长线潜力。
TREND_HISTORY_MAX_GAME_AGE_DAYS = 180
# 每日快照保留天数；同时决定“较峰值”的峰值窗口。
TREND_HISTORY_KEEP_DAYS = 14
# 至少有这么多天快照（含当天）才计算长线指标，不足时卡片显示“数据积累中”。
LONG_TERM_MIN_RECORDED_DAYS = 3
# 在线趋势：当天 CCU 与之前若干天均值比较；窗口内至少要有 2 天数据。
LONG_TERM_TREND_COMPARE_DAYS = 3
LONG_TERM_TREND_MIN_BASELINE_DAYS = 2
# 在线趋势分档：(涨跌比例下限, 得分)，从高到低匹配第一档；都不满足时为平稳 0 分。
LONG_TERM_TREND_RISE_TIERS: tuple[tuple[float, int], ...] = ((0.30, 3), (0.10, 1))
LONG_TERM_TREND_FALL_TIERS: tuple[tuple[float, int], ...] = ((-0.30, -3), (-0.10, -1))
# 可持续性：当天 CCU 占窗口内峰值的比例。
LONG_TERM_PEAK_HOLD_RATIO = 0.8
LONG_TERM_PEAK_HOLD_SCORE = 2
LONG_TERM_PEAK_COLLAPSE_RATIO = 0.5
LONG_TERM_PEAK_COLLAPSE_SCORE = -2
# 可持续性：连续在榜（每天都有快照）达到该天数加分。
LONG_TERM_BOARD_STREAK_DAYS = 7
LONG_TERM_BOARD_STREAK_SCORE = 1
# 估算单局时长（分钟）= 区间平均 CCU × 1440 ÷ 日均新增访问；只有每天一次快照，只适合跨天比较。
LONG_TERM_SESSION_LONG_MINUTES = 20
LONG_TERM_SESSION_LONG_SCORE = 2
LONG_TERM_SESSION_SHORT_MINUTES = 10
LONG_TERM_SESSION_SHORT_SCORE = -1
# 超过该时长视为挂机类游戏，估算值失真，不加分。
LONG_TERM_SESSION_AFK_MINUTES = 120
# 新增投票好评率：区间内新增投票少于该数时改用累计好评率，避免小样本波动。
LONG_TERM_RATING_MIN_NEW_VOTES = 50
LONG_TERM_RATING_HIGH = 0.90
LONG_TERM_RATING_HIGH_SCORE = 1
LONG_TERM_RATING_LOW = 0.75
LONG_TERM_RATING_LOW_SCORE = -2
# 口碑走势：累计好评率较若干天前上升达到该值（百分点）加分。
LONG_TERM_RATING_TREND_DAYS = 3
LONG_TERM_RATING_TREND_MIN_POINTS = 0.03
LONG_TERM_RATING_TREND_SCORE = 1
# 变现：看收入榜一周走势；一周上升或下滑达到该名次时分别加减分，走势平稳但在前 N 名时加基础分。
LONG_TERM_EARNING_WEEK_RISE_STEP = 30
LONG_TERM_EARNING_WEEK_RISE_SCORE = 2
LONG_TERM_EARNING_WEEK_FALL_STEP = 30
LONG_TERM_EARNING_WEEK_FALL_SCORE = -1
LONG_TERM_EARNING_RANK_LIMIT = 100
LONG_TERM_EARNING_SCORE = 1
# “长线潜力”最多展示条数与最低长线分，没有游戏达到时不硬凑。
LONG_TERM_MAX_ENTRIES = 3
LONG_TERM_MIN_SCORE = 3

# ---------------------------------------------------------------------------
# 品类风向
# ---------------------------------------------------------------------------

# 热门榜前 N 名用于统计主流品类。
GENRE_TRENDING_TOP_SIZE = 20
# 品类至少出现的款数，低于该值不写入风向，避免“1 款也算趋势”。
GENRE_MIN_COUNT = 2
