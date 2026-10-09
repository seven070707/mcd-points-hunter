"""积分抽奖期望值（EV）决策引擎。

抽奖的本质是一次带概率的投资。活动页通常只给你一张奖品清单，
却不告诉你期望收益 —— 因为算出来往往不好看。

本模块把它算清楚，回答一个问题：
**这批积分该拿去抽奖，还是该拿去商城换券？**

三件事：
1. 期望值 EV = Σ(中奖概率 × 奖品价值)，折算成"每积分期望收益"；
2. 与商城基准横向对比得到真实 ROI —— 积分的机会成本是它在商城能换到的权益，
   而不是积分的个数本身；
3. 蒙特卡洛回测：固定随机种子模拟上万次，给出亏损概率与收益分布。
"""

from __future__ import annotations

import random
from typing import Any, Mapping

from .common import as_int, as_list, as_number, normalize_probabilities, pick

_MC_TRIALS = 20000
_MC_SEED = 42

_PRIZE_LIST_KEYS = ("prizes", "prizeList", "awards", "rewards", "items", "list", "prizeItems")
_PROB_KEYS = ("probability", "prob", "rate", "chance", "odds", "percent", "winRate", "weight")
_PRIZE_NAME_KEYS = ("name", "prizeName", "title", "awardName", "desc")
_PRIZE_VALUE_KEYS = ("value", "faceValue", "amount", "worth", "cashValue", "price", "marketValue")
_PRIZE_LEVEL_KEYS = ("level", "grade", "tier", "prizeLevel", "type")

_STANCE_LABEL = {
    "strong_buy": "值得投入",
    "buy": "可以尝试（建议半仓）",
    "free_only": "只抽免费次数",
    "need_basis": "缺少基准，仅建议免费次数",
}

_GRAND_LEVEL_HINTS = ("grand", "top", "first", "special", "特", "大", "头")


def _extract_prizes(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, Mapping)]
    if isinstance(payload, Mapping):
        for key in _PRIZE_LIST_KEYS:
            inner = payload.get(key)
            if isinstance(inner, list):
                return [p for p in inner if isinstance(p, Mapping)]
    return []


def _parse_probabilities(rows: list[Mapping[str, Any]]) -> tuple[list[float], float, str]:
    """解析并归一化中奖概率。返回 (概率列表, 归一化前总和, 置信度)。"""
    raw = [as_number(pick(r, _PROB_KEYS)) for r in rows]
    total = sum(raw)

    if total <= 0:
        # 完全没有概率字段，退化为等概率假设
        probs, _ = normalize_probabilities([1.0] * len(rows))
        return probs, 0.0, "low"

    # 兼容"百分数"写法（0.5 表示 0.5%，或 50 表示 50%）
    if total > 1.0 and total <= 100.0:
        raw = [r / 100.0 for r in raw]
        total = sum(raw)

    probs, _ = normalize_probabilities(raw)
    confidence = "high" if abs(total - 1.0) <= 0.05 else "low"
    return probs, total, confidence


def _value_of(prize: Mapping[str, Any]) -> float:
    """取奖品价值（元）。拿不到就按 0 计 —— 宁可低估，绝不臆造。"""
    return max(as_number(pick(prize, _PRIZE_VALUE_KEYS)), 0.0)


def _is_grand(prize: Mapping[str, Any], value: float, threshold: float) -> bool:
    level = str(pick(prize, _PRIZE_LEVEL_KEYS, "")).lower()
    if any(h in level for h in _GRAND_LEVEL_HINTS):
        return True
    return value >= threshold


def _simulate(
    prizes: list[dict],
    draws: int,
    opportunity_cost_per_paid_draw: float,
    paid_draws: int,
    trials: int = _MC_TRIALS,
) -> dict:
    """蒙特卡洛回测：固定随机种子，结果可复现。

    成本口径是"机会成本"（元），即这些积分若拿去商城最多能换到的权益价值。
    免费抽奖次数（每日次数、抽奖券）不消耗积分，成本为 0。
    """
    if draws <= 0:
        return {"trials": 0, "note": "未产生模拟样本（建议抽奖次数为 0）。"}

    rng = random.Random(_MC_SEED)
    values = [p["value"] for p in prizes]
    probs = [p["probability"] for p in prizes]
    total_cost = opportunity_cost_per_paid_draw * paid_draws

    nets: list[float] = []
    grand_hits = 0
    for _ in range(trials):
        gain = 0.0
        hit_grand = False
        for _ in range(draws):
            idx = rng.choices(range(len(values)), weights=probs, k=1)[0]
            gain += values[idx]
            if prizes[idx]["isGrand"]:
                hit_grand = True
        nets.append(gain - total_cost)
        if hit_grand:
            grand_hits += 1

    nets.sort()
    n = len(nets)
    losses = sum(1 for v in nets if v < -1e-9)

    return {
        "trials": trials,
        "drawsPerTrial": draws,
        "paidDrawsPerTrial": paid_draws,
        "totalOpportunityCost": round(total_cost, 2),
        "meanNet": round(sum(nets) / n, 2),
        "medianNet": round(nets[n // 2], 2),
        "p05Net": round(nets[int(n * 0.05)], 2),
        "p95Net": round(nets[int(n * 0.95)], 2),
        "lossProbability": round(losses / n, 4),
        "grandHitProbability": round(grand_hits / trials, 4),
        "seed": _MC_SEED,
    }


def evaluate_lottery(
    activity: Mapping[str, Any] | None,
    point_value: float | None = None,
) -> dict:
    """评估积分抽奖的期望收益并给出投入建议。

    Args:
        activity: `query-lottery-info` 的原始返回，可附带 userResources。
        point_value: 每积分的机会成本（元/积分），通常取商城中兑换效率最高商品的
            每积分价值。**只有传入该基准，才能算出真实的投入产出比** ——
            因为积分本身不是钱，它在商城能换到的权益才是它的价值。

    Returns:
        含 EV、每积分期望收益、相对 ROI、推荐抽奖次数、模拟结果与建议的报告字典。
    """
    activity = activity or {}
    prize_rows = _extract_prizes(activity)

    if not prize_rows:
        return {
            "activityName": str(pick(activity, ("activityName", "name", "title"), "积分抽奖")),
            "confidence": "low",
            "note": "未解析到奖品列表，请确认已调用 query-lottery-info 并传入其返回值。",
            "advice": [],
        }

    probs, prob_sum, confidence = _parse_probabilities(prize_rows)
    values = [_value_of(p) for p in prize_rows]

    max_value = max(values) if values else 0.0
    grand_threshold = max_value * 0.8

    prizes: list[dict] = []
    for row, prob, value in zip(prize_rows, probs, values):
        prizes.append(
            {
                "name": str(pick(row, _PRIZE_NAME_KEYS, "未命名奖品")),
                "probability": round(prob, 6),
                "value": round(value, 2),
                "expectedValue": round(prob * value, 4),
                "isGrand": _is_grand(row, value, grand_threshold),
            }
        )

    ev_per_draw = sum(p["expectedValue"] for p in prizes)

    cost_block = activity.get("costPerDraw") or activity.get("cost") or {}
    if not isinstance(cost_block, Mapping):
        cost_block = {}
    cost_points = as_int(pick(cost_block, ("points", "point", "integral", "score")))
    cost_tickets = as_int(pick(cost_block, ("tickets", "ticket", "coupons", "times")))
    if cost_points == 0 and cost_tickets == 0:
        cost_points = as_int(pick(activity, ("costPoints", "pointsPerDraw", "unitPoints")))

    resources = activity.get("userResources") or activity.get("resources") or {}
    if not isinstance(resources, Mapping):
        resources = {}
    available_points = as_int(pick(resources, ("availablePoints", "points", "balance")))
    remaining_draws = as_int(pick(resources, ("remainingDraws", "remainTimes", "freeTimes", "leftDraws")))
    tickets = as_int(pick(resources, ("tickets", "ticket", "ticketCount", "coupons")))
    daily_limit = as_int(pick(activity, ("dailyLimit", "dayLimit", "limitPerDay")))

    free_draws = remaining_draws + tickets
    paid_capacity = (available_points // cost_points) if cost_points > 0 else 0
    if cost_points <= 0 and daily_limit > 0:
        paid_capacity = max(daily_limit - free_draws, 0)

    total_capacity = free_draws + paid_capacity
    if daily_limit > 0:
        total_capacity = min(total_capacity, max(daily_limit, free_draws))

    # 每积分的期望收益（绝对指标，不依赖任何基准）
    value_per_point = (ev_per_draw / cost_points) if cost_points > 0 else None

    # 相对 ROI：抽奖每积分期望 / 积分的机会成本
    has_basis = bool(point_value and point_value > 0 and cost_points > 0)
    roi = (value_per_point / point_value) if (has_basis and value_per_point is not None) else None
    opportunity_cost_per_draw = (cost_points * point_value) if has_basis else 0.0

    if cost_points <= 0:
        stance = "strong_buy"
    elif roi is None:
        stance = "need_basis"
    elif roi >= 1.2:
        stance = "strong_buy"
    elif roi >= 1.0:
        stance = "buy"
    else:
        stance = "free_only"

    if stance == "strong_buy":
        recommended_paid = paid_capacity
    elif stance == "buy":
        # 优势薄，只投入一半本金控制波动
        recommended_paid = paid_capacity // 2
    else:
        recommended_paid = 0

    recommended_total = free_draws + recommended_paid
    expected_return = ev_per_draw * recommended_total
    expected_cost = opportunity_cost_per_draw * recommended_paid
    expected_net = expected_return - expected_cost

    # 两套情景回测：推荐方案 vs 冲动抽满方案
    simulation = _simulate(prizes, recommended_total, opportunity_cost_per_draw, recommended_paid)
    stress_simulation = None
    if total_capacity > recommended_total:
        stress_simulation = _simulate(prizes, total_capacity, opportunity_cost_per_draw, paid_capacity)

    advice: list[str] = []
    advice.append(
        f"单次抽奖消耗 {cost_points} 积分，期望换回 {round(ev_per_draw, 2)} 元权益"
        + (f"，即每积分 {round(value_per_point, 5)} 元。" if value_per_point is not None else "。")
    )

    if stance == "need_basis":
        advice.append(
            "未提供积分价值基准，无法判断付费抽奖是否划算。"
            "把商城最优兑换的每积分价值传进来（或用 /report 综合模式），即可得出真实投入产出比。"
        )
    elif stance == "free_only":
        advice.append(
            f"投入产出比仅 {round(roi, 3)}（低于 1 表示抽奖不如直接去商城换券），"
            "付费抽奖长期看是亏的；建议只消化免费次数。"
        )
    elif stance == "buy":
        advice.append(
            f"投入产出比 {round(roi, 3)}，略优于商城但优势不厚，因此建议只用一半积分尝试，留一半继续换券。"
        )
    elif stance == "strong_buy" and roi is not None:
        advice.append(f"投入产出比 {round(roi, 3)}，明显优于商城换券，可以放手投入。")

    if free_draws > 0:
        advice.append(f"你手上有 {free_draws} 次零成本抽奖机会，无论期望值高低都应抽完。")

    if recommended_total > 0:
        if recommended_paid == 0:
            advice.append(
                f"模拟 {simulation['trials']} 次：{free_draws} 次免费抽奖零投入，"
                f"期望获得 {round(simulation.get('meanNet', 0), 2)} 元权益，"
                f"中大奖概率 {round(simulation.get('grandHitProbability', 0) * 100, 2)}%。"
            )
        else:
            advice.append(
                f"模拟 {simulation['trials']} 次：抽 {recommended_total} 次，"
                f"亏损概率 {round(simulation.get('lossProbability', 0) * 100, 1)}%，"
                f"收益中位数 {round(simulation.get('medianNet', 0), 2)} 元，"
                f"中大奖概率 {round(simulation.get('grandHitProbability', 0) * 100, 2)}%。"
            )
    if stress_simulation and stress_simulation.get("trials"):
        advice.append(
            f"对照情景：若把 {available_points} 积分全部投入（{total_capacity} 次），"
            f"亏损概率 {round(stress_simulation.get('lossProbability', 0) * 100, 1)}%，"
            f"收益中位数 {round(stress_simulation.get('medianNet', 0), 2)} 元。"
        )

    if confidence == "low":
        advice.append(
            f"注意：奖品概率字段缺失或合计为 {round(prob_sum, 4)}（理论上应为 1），"
            "以上结果基于归一化估算，仅供参考。"
        )

    mall_comparison = None
    if has_basis and value_per_point is not None:
        delta = value_per_point - point_value
        mall_comparison = {
            "lotteryValuePerPoint": round(value_per_point, 6),
            "pointValue": round(point_value, 6),
            "deltaPerPoint": round(delta, 6),
            "winner": "lottery" if delta > 0 else "mall",
        }
        if delta > 0:
            advice.append(
                f"横向对比：抽奖每积分期望 {round(value_per_point, 5)} 元，高于商城最优兑换 "
                f"{round(point_value, 5)} 元 —— 这批积分拿去抽奖比换券更值。"
            )
        else:
            advice.append(
                f"横向对比：抽奖每积分期望 {round(value_per_point, 5)} 元，低于商城最优兑换 "
                f"{round(point_value, 5)} 元 —— 同样的积分，去商城换券收益更高。"
            )

    return {
        "activityName": str(pick(activity, ("activityName", "name", "title"), "积分抽奖")),
        "status": str(pick(activity, ("status", "state"), "unknown")),
        "confidence": confidence,
        "probabilitySumRaw": round(prob_sum, 4),
        "prizeCount": len(prizes),
        "prizes": prizes,
        "expectedValuePerDraw": round(ev_per_draw, 4),
        "costPerDrawPoints": cost_points,
        "valuePerPoint": round(value_per_point, 6) if value_per_point is not None else None,
        "roi": round(roi, 4) if roi is not None else None,
        "hasValueBasis": has_basis,
        "resource": {
            "availablePoints": available_points,
            "freeDraws": free_draws,
            "affordablePaidDraws": paid_capacity,
            "maxDraws": total_capacity,
            "dailyLimit": daily_limit or None,
        },
        "plan": {
            "stance": stance,
            "stanceLabel": _STANCE_LABEL[stance],
            "recommendedPaidDraws": recommended_paid,
            "recommendedTotalDraws": recommended_total,
            "pointsOutlay": recommended_paid * cost_points,
            "expectedReturn": round(expected_return, 2),
            "expectedOpportunityCost": round(expected_cost, 2),
            "expectedNet": round(expected_net, 2),
        },
        "simulation": simulation,
        "stressSimulation": stress_simulation,
        "mallComparison": mall_comparison,
        "advice": advice,
    }
