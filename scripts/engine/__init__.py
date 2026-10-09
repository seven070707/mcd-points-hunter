"""mcd-points-hunter 核心计算引擎。

设计原则：本包只做纯计算，不发起任何网络请求。
麦当劳 MCP 的数据抓取由 WorkBuddy 智能体层完成，原始 JSON 再交给本引擎处理，
因此全部逻辑都可以完全离线自测。

三个子模块：
    expiry  -- 积分到期风险与止损速率
    mall    -- 麦麦商城兑换划算度排序
    lottery -- 积分抽奖期望值（EV）决策
"""

from .expiry import assess_expiry
from .lottery import evaluate_lottery
from .mall import rank_mall_roi

__version__ = "1.0.0"
__all__ = ["assess_expiry", "rank_mall_roi", "evaluate_lottery"]
