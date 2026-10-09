#!/usr/bin/env python3
"""麦麦积分猎人 · 命令行入口。

用法示例：
    python scripts/points_hunter.py demo
    python scripts/points_hunter.py audit   --account  examples/account.sample.json
    python scripts/points_hunter.py mall    --products examples/mall-products.sample.json
    python scripts/points_hunter.py lottery --activity examples/lottery.sample.json
    python scripts/points_hunter.py report  --account examples/account.sample.json \
                                            --products examples/mall-products.sample.json \
                                            --activity examples/lottery.sample.json

所有子命令都支持 --json 输出原始结构化结果，便于二次集成。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from engine import assess_expiry, evaluate_lottery, rank_mall_roi  # noqa: E402

LINE = "=" * 66
THIN = "-" * 66


# --------------------------------------------------------------------------- #
# 输出工具
# --------------------------------------------------------------------------- #
def _display_width(text: str) -> int:
    """中日韩字符按 2 列计算，用于终端表格对齐。"""
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in str(text))


def _pad(text: str, width: int, align: str = "left") -> str:
    text = str(text)
    gap = max(width - _display_width(text), 0)
    return (" " * gap + text) if align == "right" else (text + " " * gap)


def _money(value: float) -> str:
    return f"{value:,.2f}"


def _int(value: int) -> str:
    return f"{value:,}"


def _title(text: str) -> None:
    print()
    print(f"[{text}]")


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #
def render_audit(report: dict) -> None:
    _title("积分账户概览")
    print(f"  可用积分        {_int(report.get('availablePoints', 0))}")
    print(f"  累计积分        {_int(report.get('totalPoints', 0))}")
    print(f"  冻结积分        {_int(report.get('frozenPoints', 0))}")

    exp = report.get("expiring", {})
    print()
    print(f"  风险等级        {report.get('riskLabel', '-')}  ({report.get('riskLevel', '-')})")
    print(f"  临期积分总计    {_int(exp.get('total', 0))}")
    print(f"  高危（30 天内） {_int(exp.get('atRisk', 0))}")
    if exp.get("nextDeadline"):
        print(f"  最近到期日      {exp['nextDeadline']}  剩余 {exp.get('daysToNextDeadline')} 天")

    items = exp.get("items") or []
    if items:
        print()
        headers = ("到期日", "剩余天数", "积分数", "每天需消耗", "等级")
        widths = (12, 9, 10, 11, 7)
        print("  " + "".join(_pad(h, w) for h, w in zip(headers, widths)))
        print("  " + THIN[:60])
        for item in items:
            row = (
                item.get("expireDate", "-"),
                item.get("daysLeft", "-"),
                _int(item.get("points", 0)),
                f"{item.get('dailyQuota', 0):g}",
                item.get("levelLabel", "-"),
            )
            print("  " + "".join(_pad(c, w) for c, w in zip(row, widths)))

    advice = report.get("advice") or []
    if advice:
        _title("行动建议")
        for i, tip in enumerate(advice, 1):
            print(f"  {i}. {tip}")


def render_mall(report: dict) -> None:
    if report.get("count", 0) == 0:
        print(f"  {report.get('note', '无可用商品数据。')}")
        return

    _title("商城兑换划算度排行")
    headers = ("名次", "商品", "消耗积分", "权益价值", "每千分价值", "评级")
    widths = (5, 26, 10, 10, 11, 7)
    print("  " + "".join(_pad(h, w) for h, w in zip(headers, widths)))
    print("  " + THIN[:62])
    for i, item in enumerate(report.get("top", []), 1):
        row = (
            i,
            str(item.get("name", ""))[:24],
            _int(item.get("points", 0)),
            _money(item.get("referenceValue", 0)),
            _money(item.get("valuePer1000Points", 0)),
            {"top": "优选", "mid": "一般", "low": "偏低"}.get(item.get("grade"), "-"),
        )
        print("  " + "".join(_pad(c, w) for c, w in zip(row, widths)))

    print()
    print(f"  共解析 {report.get('count')} 件商品")
    if report.get("spreadRatio"):
        print(f"  极差 {report['spreadRatio']} 倍（最高 {_money(report['bestPer1000Points'])} 元/千分"
              f" vs 最低 {_money(report['worstPer1000Points'])} 元/千分）")

    advice = report.get("advice") or []
    if advice:
        _title("选购建议")
        for i, tip in enumerate(advice, 1):
            print(f"  {i}. {tip}")


def render_lottery(report: dict) -> None:
    if not report.get("prizes"):
        print(f"  {report.get('note', '无可用抽奖数据。')}")
        return

    _title("抽奖期望值分析")
    print(f"  活动名称        {report.get('activityName')}")
    print(f"  单次消耗        {_int(report.get('costPerDrawPoints', 0))} 积分")
    print(f"  单次期望收益    {_money(report.get('expectedValuePerDraw', 0))} 元")
    vpp = report.get("valuePerPoint")
    if vpp is not None:
        print(f"  每积分期望收益  {vpp:.5f} 元")
    roi = report.get("roi")
    print(f"  投入产出比      {roi if roi is not None else '无法计算（缺少积分价值基准）'}")
    print(f"  数据置信度      {report.get('confidence')}")

    print()
    headers = ("奖品", "中奖概率", "价值", "期望贡献")
    widths = (26, 11, 10, 10)
    print("  " + "".join(_pad(h, w) for h, w in zip(headers, widths)))
    print("  " + THIN[:58])
    for prize in report.get("prizes", []):
        row = (
            str(prize.get("name", ""))[:24],
            f"{prize.get('probability', 0) * 100:.3f}%",
            _money(prize.get("value", 0)),
            _money(prize.get("expectedValue", 0)),
        )
        print("  " + "".join(_pad(c, w) for c, w in zip(row, widths)))

    plan = report.get("plan", {})
    res = report.get("resource", {})
    _title("投入建议")
    print(f"  结论            {plan.get('stanceLabel')}  ({plan.get('stance')})")
    print(f"  免费抽奖机会    {res.get('freeDraws', 0)} 次")
    print(f"  建议付费次数    {plan.get('recommendedPaidDraws', 0)} 次")
    print(f"  建议总次数      {plan.get('recommendedTotalDraws', 0)} 次")
    print(f"  积分支出        {_int(plan.get('pointsOutlay', 0))}")
    print(f"  期望收益        {_money(plan.get('expectedReturn', 0))} 元")
    if report.get("hasValueBasis"):
        print(f"  积分机会成本    {_money(plan.get('expectedOpportunityCost', 0))} 元")
    print(f"  期望净收益      {_money(plan.get('expectedNet', 0))} 元")

    sim = report.get("simulation") or {}
    if sim.get("trials"):
        _title("蒙特卡洛回测")
        print(f"  模拟次数        {_int(sim['trials'])}（随机种子 {sim.get('seed')}，结果可复现）")
        print(f"  收益均值        {_money(sim.get('meanNet', 0))} 元")
        print(f"  收益中位数      {_money(sim.get('medianNet', 0))} 元")
        print(f"  5% 分位（最差） {_money(sim.get('p05Net', 0))} 元")
        print(f"  95% 分位（最好）{_money(sim.get('p95Net', 0))} 元")
        print(f"  亏损概率        {sim.get('lossProbability', 0) * 100:.1f}%")
        print(f"  中大奖概率      {sim.get('grandHitProbability', 0) * 100:.2f}%")

    cmp_data = report.get("mallComparison")
    if cmp_data:
        _title("抽奖 vs 商城")
        print(f"  抽奖每积分期望  {cmp_data.get('lotteryValuePerPoint')} 元")
        print(f"  商城每积分价值  {cmp_data.get('pointValue')} 元")
        print(f"  更优选择        {'抽奖' if cmp_data.get('winner') == 'lottery' else '商城换券'}")

    advice = report.get("advice") or []
    if advice:
        _title("决策解读")
        for i, tip in enumerate(advice, 1):
            print(f"  {i}. {tip}")


# --------------------------------------------------------------------------- #
# IO
# --------------------------------------------------------------------------- #
def load_json(path: str | None):
    if not path:
        return None
    file_path = Path(path)
    if not file_path.exists():
        raise SystemExit(f"找不到文件：{path}")
    with file_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def build_report(account, products, activity, today: date | None) -> dict:
    audit = assess_expiry(account, today=today) if account else None
    mall = rank_mall_roi(products) if products else None
    # 用商城中兑换效率最高商品的每积分价值，作为积分的机会成本基准
    point_value = None
    if mall and mall.get("bestPer1000Points"):
        point_value = mall["bestPer1000Points"] / 1000.0
    lottery = evaluate_lottery(activity, point_value=point_value) if activity else None
    return {"audit": audit, "mall": mall, "lottery": lottery}


def render_report(report: dict, today: date | None) -> None:
    audit, mall, lottery = report.get("audit"), report.get("mall"), report.get("lottery")

    print()
    print(LINE)
    print("  麦麦积分猎人 · 积分资产诊断报告")
    print(f"  生成日期：{(today or date.today()).isoformat()}")
    print(LINE)

    step = 1
    total = sum(1 for x in (audit, mall, lottery) if x)

    actions: list[str] = []

    if audit:
        print(f"\n--- 第 {step}/{total} 步：到期风险 ---")
        render_audit(audit)
        exp = audit.get("expiring", {})
        if exp.get("atRisk"):
            actions.append(f"在 {exp.get('daysToNextDeadline')} 天内用掉 {_int(exp['atRisk'])} 临期积分")
        step += 1

    if mall:
        print(f"\n--- 第 {step}/{total} 步：商城划算度 ---")
        render_mall(mall)
        top = (mall.get("top") or [None])[0]
        if top:
            actions.append(f"优先兑换「{top['name']}」（{top['points']} 积分，每千分价值 {top['valuePer1000Points']} 元）")
        step += 1

    if lottery:
        print(f"\n--- 第 {step}/{total} 步：抽奖决策 ---")
        render_lottery(lottery)
        plan = lottery.get("plan", {})
        actions.append(
            f"抽奖执行策略：{plan.get('stanceLabel')}，共抽 {plan.get('recommendedTotalDraws')} 次"
        )
        step += 1

    if actions:
        print()
        print(LINE)
        print("  最终行动清单")
        print(LINE)
        for i, item in enumerate(actions, 1):
            print(f"  {i}. {item}")
        print()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="points_hunter",
        description="麦麦积分猎人：把麦当劳积分从躺着过期，变成算着花掉。",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="输出原始 JSON 而非中文报告")
    common.add_argument("--today", help="指定参考日期（YYYY-MM-DD），用于复现测试")

    parser = argparse.ArgumentParser(
        prog="points_hunter",
        description="麦麦积分猎人：把麦当劳积分从躺着过期，变成算着花掉。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_audit = sub.add_parser("audit", parents=[common], help="积分到期风险分析")
    p_audit.add_argument("--account", required=True, help="query-my-account 返回的 JSON 文件")

    p_mall = sub.add_parser("mall", parents=[common], help="商城兑换划算度排序")
    p_mall.add_argument("--products", required=True, help="mall-points-products 返回的 JSON 文件")

    p_lot = sub.add_parser("lottery", parents=[common], help="抽奖期望值决策")
    p_lot.add_argument("--activity", required=True, help="query-lottery-info 返回的 JSON 文件")
    p_lot.add_argument(
        "--point-value",
        type=float,
        help="每积分机会成本（元/积分），取商城中最优兑换的每积分价值；不传则只输出绝对指标",
    )

    p_rep = sub.add_parser("report", parents=[common], help="综合诊断报告")
    p_rep.add_argument("--account")
    p_rep.add_argument("--products")
    p_rep.add_argument("--activity")

    sub.add_parser("demo", parents=[common], help="用内置样例数据跑一遍完整流程")

    args = parser.parse_args(argv)
    today = date.fromisoformat(args.today) if args.today else None

    examples = _SCRIPT_DIR.parent / "examples"

    try:
        if args.command == "audit":
            result = assess_expiry(load_json(args.account), today=today)
            render_audit(result) if not args.json else print(json.dumps(result, ensure_ascii=False, indent=2))

        elif args.command == "mall":
            result = rank_mall_roi(load_json(args.products))
            render_mall(result) if not args.json else print(json.dumps(result, ensure_ascii=False, indent=2))

        elif args.command == "lottery":
            result = evaluate_lottery(load_json(args.activity), point_value=args.point_value)
            render_lottery(result) if not args.json else print(json.dumps(result, ensure_ascii=False, indent=2))

        elif args.command == "report":
            result = build_report(
                load_json(args.account), load_json(args.products), load_json(args.activity), today
            )
            render_report(result, today) if not args.json else print(json.dumps(result, ensure_ascii=False, indent=2))

        elif args.command == "demo":
            account = load_json(str(examples / "account.sample.json"))
            products = load_json(str(examples / "mall-products.sample.json"))
            activity = load_json(str(examples / "lottery.sample.json"))
            result = build_report(account, products, activity, today)
            render_report(result, today) if not args.json else print(json.dumps(result, ensure_ascii=False, indent=2))

    except FileNotFoundError as exc:
        print(f"文件读取失败：{exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    raise SystemExit(main())
