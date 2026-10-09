"""麦麦商城兑换划算度排序。

MCP 的 `mall-points-products` 只给你商品列表，`mall-product-detail` 给你详情。
它们不会告诉你"哪个划算"——但这件事是可以算出来的。

核心指标是 **每积分价值**（元 / 积分）：

    每积分价值 = 可获得的权益面值(元) / 消耗积分

同样花 1000 积分，换到 10 元券和换到 30 元券，差 3 倍。
商城列表按积分价排序，恰好把这个差异完全掩盖掉了 —— 这就是本模块存在的理由。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .common import as_int, as_list, as_number, grade_by_quantile, pick

_PRODUCT_LIST_KEYS = ("products", "list", "items", "goods", "records")
_POINTS_KEYS = ("points", "point", "pointsCost", "needPoints", "integral", "score", "price")
_VALUE_KEYS = ("faceValue", "faceAmount", "value", "amount", "denomination", "discountAmount")
_CASH_KEYS = ("cashPrice", "price2", "money", "rmb", "cash")
_NAME_KEYS = ("name", "productName", "title", "goodsName")
_ID_KEYS = ("productId", "id", "goodsId", "skuId", "code")
_VALID_KEYS = ("validDays", "effectiveDays", "expireDays", "useDays", "validPeriod")
_TYPE_KEYS = ("type", "productType", "category", "kind")
_STOCK_KEYS = ("stock", "inventory", "remain", "quantity")

VIRTUAL_HINTS = ("券", "兑换码", "会员", "权益", "coupon", "code")


def _is_virtual(row: Mapping[str, Any]) -> bool:
    raw_type = str(pick(row, _TYPE_KEYS, "")).lower()
    if any(h in raw_type for h in ("virtual", "coupon", "code", "券")):
        return True
    name = str(pick(row, _NAME_KEYS, "")).lower()
    return any(h.lower() in name for h in VIRTUAL_HINTS)


def _extract_products(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, Mapping)]
    if isinstance(payload, Mapping):
        for key in _PRODUCT_LIST_KEYS:
            inner = payload.get(key)
            if isinstance(inner, list):
                return [p for p in inner if isinstance(p, Mapping)]
        return [payload]
    return []


def rank_mall_roi(payload: Any, top_n: int = 10) -> dict:
    """按每积分价值对商城商品排序。

    Args:
        payload: `mall-points-products` / `mall-product-detail` 的原始返回。
        top_n: 返回的优选商品数量。

    Returns:
        含排序明细、分级统计与兑换建议的报告字典。
    """
    rows = _extract_products(payload)

    entries: list[dict] = []
    for row in rows:
        points = as_int(pick(row, _POINTS_KEYS))
        if points <= 0:
            continue

        face_value = as_number(pick(row, _VALUE_KEYS))
        cash_price = as_number(pick(row, _CASH_KEYS))
        # 纯积分兑换商品：用权益面值；若拿不到面值，退化为现金等价价
        reference_value = face_value if face_value > 0 else cash_price
        if reference_value <= 0:
            continue

        per_point = reference_value / points

        entries.append(
            {
                "productId": str(pick(row, _ID_KEYS, "")),
                "name": str(pick(row, _NAME_KEYS, "未命名商品")),
                "points": points,
                "referenceValue": round(reference_value, 2),
                "valueSource": "faceValue" if face_value > 0 else "cashPrice",
                "valuePerPoint": round(per_point, 6),
                "valuePer1000Points": round(per_point * 1000, 2),
                "validDays": as_int(pick(row, _VALID_KEYS)) or None,
                "isVirtual": _is_virtual(row),
                "stock": as_int(pick(row, _STOCK_KEYS)) or None,
            }
        )

    if not entries:
        return {
            "count": 0,
            "note": "未能从输入中解析出带积分价与权益价值的商品，请确认已调用 mall-points-products 与 mall-product-detail。",
            "products": [],
            "advice": [],
        }

    all_ratios = [e["valuePerPoint"] for e in entries]
    for entry in entries:
        entry["grade"] = grade_by_quantile(all_ratios, entry["valuePerPoint"])

    entries.sort(key=lambda e: e["valuePerPoint"], reverse=True)

    top = entries[: max(top_n, 1)]
    buckets = {
        "top": sum(1 for e in entries if e["grade"] == "top"),
        "mid": sum(1 for e in entries if e["grade"] == "mid"),
        "low": sum(1 for e in entries if e["grade"] == "low"),
    }

    best = entries[0]
    worst = entries[-1]
    spread = (
        round(best["valuePerPoint"] / worst["valuePerPoint"], 2)
        if worst["valuePerPoint"] > 0
        else None
    )

    advice: list[str] = []
    advice.append(
        f"最划算的是「{best['name']}」：{best['points']} 积分换 {best['referenceValue']} 元，"
        f"每 1000 积分价值 {best['valuePer1000Points']} 元。"
    )
    if spread and spread >= 1.5:
        advice.append(
            f"同一批商品里单位积分价值差最高达 {spread} 倍 —— 随手挑一个，可能就亏掉一半积分。"
        )
    short_lived = [e for e in entries if e["validDays"] and e["validDays"] <= 15]
    if short_lived:
        names = "、".join(e["name"] for e in short_lived[:3])
        advice.append(f"注意有效期短的商品（15 天内）：{names}，兑换前先确认用得完。")

    return {
        "count": len(entries),
        "asOfProducts": len(entries),
        "buckets": buckets,
        "bestPer1000Points": best["valuePer1000Points"],
        "worstPer1000Points": worst["valuePer1000Points"],
        "spreadRatio": spread,
        "top": top,
        "products": entries,
        "advice": advice,
    }
