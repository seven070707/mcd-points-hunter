"""积分到期风险分析。

麦当劳积分有有效期，`query-my-account` 会返回"即将过期积分"。
但一个静态数字没有行动意义 —— 用户需要知道的是：
**还剩几天、每天至少要花掉多少、现在不处理会损失多少。**

本模块把静态数字翻译成可执行的止损计划。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping

from .common import as_int, as_list, pick

# 风险分级的时间阈值（天）
CRITICAL_DAYS = 7
WARNING_DAYS = 30
WATCH_DAYS = 60

LEVEL_ORDER = {"expired": 0, "critical": 1, "warning": 2, "watch": 3, "safe": 4}

LEVEL_LABEL = {
    "expired": "已过期",
    "critical": "紧急",
    "warning": "警告",
    "watch": "关注",
    "safe": "安全",
}

_DETAIL_KEYS = (
    "expiringDetails",
    "expiringDetail",
    "expireDetails",
    "expiringItems",
    "expiringList",
    "expiryItems",
    "details",
)

_EXPIRING_KEYS = (
    "expiringPoints",
    "expiringPoint",
    "willExpirePoints",
    "aboutToExpirePoints",
    "expirePoints",
)

_AVAILABLE_KEYS = ("availablePoints", "availablePoint", "points", "balance", "usablePoints")
_TOTAL_KEYS = ("totalPoints", "totalPoint", "accumulatedPoints", "total")
_FROZEN_KEYS = ("frozenPoints", "frozenPoint", "freezePoints", "lockedPoints")


def parse_date(value: Any) -> date | None:
    """尽力把各种日期写法解析成 date，解析不出来返回 None。"""
    if value in (None, "", 0):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        # 兼容秒级与毫秒级时间戳
        ts = float(value)
        if ts > 1e11:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts).date()
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def classify(days_left: int) -> str:
    if days_left < 0:
        return "expired"
    if days_left <= CRITICAL_DAYS:
        return "critical"
    if days_left <= WARNING_DAYS:
        return "warning"
    if days_left <= WATCH_DAYS:
        return "watch"
    return "safe"


@dataclass
class ExpiryItem:
    points: int
    expire_date: date
    days_left: int
    level: str
    daily_quota: float

    def to_dict(self) -> dict:
        return {
            "points": self.points,
            "expireDate": self.expire_date.isoformat(),
            "daysLeft": self.days_left,
            "level": self.level,
            "levelLabel": LEVEL_LABEL[self.level],
            "dailyQuota": self.daily_quota,
        }


def _build_items(account: Mapping[str, Any], today: date) -> tuple[list[ExpiryItem], str]:
    """构造到期明细。返回 (明细列表, 置信度)。"""
    details = as_list(pick(account, _DETAIL_KEYS))
    items: list[ExpiryItem] = []
    confidence = "high"

    if details:
        for row in details:
            if not isinstance(row, Mapping):
                continue
            points = as_int(pick(row, ("points", "point", "amount", "value", "quantity")))
            expire_date = parse_date(
                pick(row, ("expireDate", "expiredDate", "expiryDate", "deadline", "endDate", "date"))
            )
            if points <= 0 or expire_date is None:
                continue
            days_left = (expire_date - today).days
            level = classify(days_left)
            quota = round(points / days_left, 2) if days_left > 0 else float(points)
            items.append(ExpiryItem(points, expire_date, days_left, level, quota))

    if items:
        return items, confidence

    # 降级路径：只有总数、没有明细。假设一个保守的 30 天窗口并标注低置信度。
    total_expiring = as_int(pick(account, _EXPIRING_KEYS))
    if total_expiring > 0:
        expire_date = date.fromordinal(today.toordinal() + WARNING_DAYS)
        days_left = WARNING_DAYS
        items.append(
            ExpiryItem(
                total_expiring,
                expire_date,
                days_left,
                classify(days_left),
                round(total_expiring / days_left, 2),
            )
        )
        confidence = "low"
    return items, confidence


def assess_expiry(account: Mapping[str, Any] | None, today: date | None = None) -> dict:
    """分析积分账户的到期风险。

    Args:
        account: `query-my-account` 的原始返回（或等价结构的字典）。
        today: 参考日期，默认取系统当天；测试时可显式传入。

    Returns:
        含风险等级、剩余天数、每日止损额度与行动建议的报告字典。
    """
    account = account or {}
    today = today or date.today()

    items, confidence = _build_items(account, today)
    items.sort(key=lambda i: (i.days_left, -i.points))

    total_expiring = sum(i.points for i in items)
    at_risk_points = sum(i.points for i in items if i.level in ("critical", "warning"))
    expired_points = sum(i.points for i in items if i.level == "expired")

    if items:
        worst = min(items, key=lambda i: i.days_left)
        risk_level = worst.level
        next_deadline = worst.expire_date.isoformat()
        days_to_next = worst.days_left
    else:
        risk_level = "safe"
        next_deadline = None
        days_to_next = None

    advice: list[str] = []
    if expired_points > 0:
        advice.append(f"已有 {expired_points} 积分过期作废，建议核对账户明细。")
    if at_risk_points > 0:
        urgent = [i for i in items if i.level == "critical"]
        if urgent:
            need = sum(i.points for i in urgent)
            gap = min(i.days_left for i in urgent)
            advice.append(
                f"{gap} 天内必须消耗 {need} 积分，否则直接作废；"
                f"折算每天至少要用掉 {round(need / max(gap, 1), 1)} 积分。"
            )
        warn = [i for i in items if i.level == "warning"]
        if warn:
            need = sum(i.points for i in warn)
            advice.append(f"另有 {need} 积分在 30 天内到期，建议本周内一并规划兑换。")
    if not items:
        advice.append("未检测到临期积分，账户状态健康。")
    if confidence == "low":
        advice.append("注意：账户未返回逐笔到期明细，以上按 30 天窗口估算，请以麦当劳 App 实际到期日为准。")

    return {
        "asOf": today.isoformat(),
        "availablePoints": as_int(pick(account, _AVAILABLE_KEYS)),
        "totalPoints": as_int(pick(account, _TOTAL_KEYS)),
        "frozenPoints": as_int(pick(account, _FROZEN_KEYS)),
        "confidence": confidence,
        "riskLevel": risk_level,
        "riskLabel": LEVEL_LABEL[risk_level],
        "expiring": {
            "total": total_expiring,
            "atRisk": at_risk_points,
            "expired": expired_points,
            "nextDeadline": next_deadline,
            "daysToNextDeadline": days_to_next,
            "items": [i.to_dict() for i in items],
        },
        "advice": advice,
    }
