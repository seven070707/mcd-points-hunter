"""通用取值与数值解析工具。

麦当劳 MCP 的返回字段在不同 Tool、不同版本之间存在命名差异，
这里统一做一层兼容映射，避免业务代码到处写 ``row.get("a") or row.get("b")``。
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

_NUMBER_CLEAN_RE = re.compile(r"[^\d.\-]")


def pick(row: Mapping[str, Any], keys: Sequence[str], default: Any = None) -> Any:
    """按候选字段名顺序取第一个非空值。"""
    for key in keys:
        if key in row:
            value = row[key]
            if value is not None and value != "":
                return value
    return default


def as_number(value: Any, default: float = 0.0) -> float:
    """把 "1,500" / "1500分" / "¥15.00" 之类的写法解析成 float。"""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    cleaned = _NUMBER_CLEAN_RE.sub("", text)
    if cleaned in ("", "-", "."):
        return default
    try:
        return float(cleaned)
    except ValueError:
        return default


def as_int(value: Any, default: int = 0) -> int:
    return int(round(as_number(value, float(default))))


def as_list(value: Any) -> list:
    """把可能是 None / 单对象 / 列表 / {"list": [...]} 的返回值统一成列表。"""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, Mapping):
        for key in ("list", "items", "records", "data", "results", "products", "prizes"):
            inner = value.get(key)
            if isinstance(inner, list):
                return inner
        return [value]
    return [value]


def normalize_probabilities(weights: Iterable[float]) -> tuple[list[float], float]:
    """把一组概率/权重归一化。

    返回 (归一化概率列表, 原始总和)。原始总和与 1 偏差过大时，
    调用方应据此降低结果置信度。
    """
    values = [max(float(w), 0.0) for w in weights]
    total = sum(values)
    if total <= 0:
        n = len(values)
        return ([1.0 / n] * n if n else []), 0.0
    return [v / total for v in values], total


def grade_by_quantile(values: Sequence[float], value: float) -> str:
    """按分位数给出相对评级，避免硬编码绝对阈值。"""
    if not values:
        return "unknown"
    ordered = sorted(values)
    n = len(ordered)
    if n == 1:
        return "top"
    rank = sum(1 for v in ordered if v <= value)
    ratio = rank / n
    if ratio > 0.75:
        return "top"
    if ratio > 0.25:
        return "mid"
    return "low"
