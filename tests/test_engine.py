"""mcd-points-hunter 引擎单元测试。

运行方式（在项目根目录）：
    python tests/test_engine.py
    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from engine import assess_expiry, evaluate_lottery, rank_mall_roi  # noqa: E402
from engine.common import as_number, grade_by_quantile, normalize_probabilities  # noqa: E402
from engine.expiry import classify, parse_date  # noqa: E402


class TestCommon(unittest.TestCase):
    def test_as_number_handles_messy_input(self):
        self.assertEqual(as_number("1,500"), 1500.0)
        self.assertEqual(as_number("¥15.00"), 15.0)
        self.assertEqual(as_number("1500分"), 1500.0)
        self.assertEqual(as_number(42), 42.0)
        self.assertEqual(as_number(None, 7.0), 7.0)
        self.assertEqual(as_number("abc", 3.0), 3.0)
        self.assertEqual(as_number(True, 5.0), 5.0)

    def test_normalize_probabilities(self):
        probs, total = normalize_probabilities([1, 3])
        self.assertAlmostEqual(sum(probs), 1.0)
        self.assertEqual(total, 4.0)
        self.assertAlmostEqual(probs[1], 0.75)

    def test_normalize_all_zero_falls_back_to_uniform(self):
        probs, total = normalize_probabilities([0, 0, 0])
        self.assertEqual(total, 0.0)
        self.assertAlmostEqual(sum(probs), 1.0)
        self.assertAlmostEqual(probs[0], 1 / 3)

    def test_grade_by_quantile(self):
        values = [1.0, 2.0, 3.0, 4.0]
        self.assertEqual(grade_by_quantile(values, 4.0), "top")
        self.assertEqual(grade_by_quantile(values, 1.0), "low")
        self.assertEqual(grade_by_quantile([], 1.0), "unknown")


class TestExpiry(unittest.TestCase):
    def test_classify_boundaries(self):
        self.assertEqual(classify(-1), "expired")
        self.assertEqual(classify(0), "critical")
        self.assertEqual(classify(7), "critical")
        self.assertEqual(classify(8), "warning")
        self.assertEqual(classify(30), "warning")
        self.assertEqual(classify(31), "watch")
        self.assertEqual(classify(60), "watch")
        self.assertEqual(classify(61), "safe")

    def test_parse_date_formats(self):
        self.assertEqual(parse_date("2026-10-15"), date(2026, 10, 15))
        self.assertEqual(parse_date("2026/10/15"), date(2026, 10, 15))
        self.assertEqual(parse_date("20261015"), date(2026, 10, 15))
        self.assertEqual(parse_date("2026-10-15 08:30:00"), date(2026, 10, 15))
        self.assertIsNone(parse_date("not-a-date"))
        self.assertIsNone(parse_date(None))
        self.assertIsNone(parse_date(""))

    def test_detects_urgent_expiry(self):
        account = {
            "availablePoints": 1000,
            "expiringDetails": [
                {"points": 500, "expireDate": "2026-10-12"},
                {"points": 200, "expireDate": "2026-12-01"},
            ],
        }
        report = assess_expiry(account, today=date(2026, 10, 9))
        self.assertEqual(report["riskLevel"], "critical")
        self.assertEqual(report["expiring"]["total"], 700)
        self.assertEqual(report["expiring"]["atRisk"], 500)
        self.assertEqual(report["expiring"]["daysToNextDeadline"], 3)
        self.assertEqual(report["confidence"], "high")

    def test_daily_quota_computation(self):
        account = {"expiringDetails": [{"points": 300, "expireDate": "2026-10-13"}]}
        report = assess_expiry(account, today=date(2026, 10, 9))
        self.assertAlmostEqual(report["expiring"]["items"][0]["dailyQuota"], 75.0)

    def test_fallback_when_details_missing(self):
        report = assess_expiry({"expiringPoints": 900}, today=date(2026, 10, 9))
        self.assertEqual(report["confidence"], "low")
        self.assertEqual(report["expiring"]["total"], 900)
        self.assertTrue(any("估算" in tip for tip in report["advice"]))

    def test_healthy_account_has_no_risk(self):
        report = assess_expiry({"availablePoints": 100}, today=date(2026, 10, 9))
        self.assertEqual(report["riskLevel"], "safe")
        self.assertEqual(report["expiring"]["total"], 0)

    def test_empty_input_does_not_crash(self):
        report = assess_expiry(None, today=date(2026, 10, 9))
        self.assertEqual(report["riskLevel"], "safe")


class TestMall(unittest.TestCase):
    def test_ranking_prefers_higher_value_per_point(self):
        payload = {
            "list": [
                {"name": "A券", "points": 1000, "faceValue": 30.0},
                {"name": "B券", "points": 1000, "faceValue": 10.0},
                {"name": "C券", "points": 500, "faceValue": 7.5},
            ]
        }
        report = rank_mall_roi(payload)
        self.assertEqual(report["count"], 3)
        self.assertEqual(report["top"][0]["name"], "A券")
        self.assertEqual(report["products"][-1]["name"], "B券")
        self.assertAlmostEqual(report["spreadRatio"], 3.0, places=2)

    def test_value_per_1000_points(self):
        report = rank_mall_roi([{"name": "X", "points": 500, "faceValue": 25.0}])
        self.assertAlmostEqual(report["products"][0]["valuePer1000Points"], 50.0)

    def test_cash_price_used_as_fallback_value(self):
        report = rank_mall_roi([{"name": "实物", "points": 1000, "cashPrice": 20.0}])
        self.assertEqual(report["products"][0]["valueSource"], "cashPrice")
        self.assertAlmostEqual(report["products"][0]["referenceValue"], 20.0)

    def test_face_value_takes_priority_over_cash(self):
        report = rank_mall_roi(
            [{"name": "组合", "points": 1000, "faceValue": 30.0, "cashPrice": 5.0}]
        )
        self.assertEqual(report["products"][0]["valueSource"], "faceValue")

    def test_products_without_usable_value_are_skipped(self):
        self.assertEqual(rank_mall_roi([{"name": "无价", "points": 100}])["count"], 0)
        self.assertEqual(rank_mall_roi({})["count"], 0)
        self.assertEqual(rank_mall_roi(None)["count"], 0)

    def test_string_number_fields_are_parsed(self):
        report = rank_mall_roi([{"name": "S", "points": "1,000", "faceValue": "¥20.00"}])
        self.assertEqual(report["count"], 1)
        self.assertAlmostEqual(report["products"][0]["valuePer1000Points"], 20.0)

    def test_warns_about_short_validity(self):
        report = rank_mall_roi(
            [{"name": "短效券", "points": 500, "faceValue": 20.0, "validDays": 7}]
        )
        self.assertTrue(any("有效期" in tip for tip in report["advice"]))


class TestLottery(unittest.TestCase):
    @staticmethod
    def _activity() -> dict:
        return {
            "activityName": "测试活动",
            "status": "active",
            "costPerDraw": {"points": 100},
            "userResources": {"availablePoints": 1000, "remainingDraws": 1, "tickets": 0},
            "prizes": [
                {"name": "大奖", "probability": 0.1, "value": 100.0},
                {"name": "小奖", "probability": 0.9, "value": 0.0},
            ],
        }

    def test_expected_value_per_draw(self):
        report = evaluate_lottery(self._activity())
        self.assertAlmostEqual(report["expectedValuePerDraw"], 10.0)
        self.assertAlmostEqual(report["valuePerPoint"], 0.1)

    def test_roi_requires_value_basis(self):
        report = evaluate_lottery(self._activity())
        self.assertIsNone(report["roi"])
        self.assertFalse(report["hasValueBasis"])
        self.assertEqual(report["plan"]["stance"], "need_basis")

    def test_roi_computed_against_mall_basis(self):
        # 每积分 0.05 元 → 100 积分机会成本 5 元；EV 10 元 → ROI 2.0
        report = evaluate_lottery(self._activity(), point_value=0.05)
        self.assertAlmostEqual(report["roi"], 2.0, places=3)
        self.assertEqual(report["plan"]["stance"], "strong_buy")
        self.assertEqual(report["mallComparison"]["winner"], "lottery")

    def test_poor_roi_only_recommends_free_draws(self):
        report = evaluate_lottery(self._activity(), point_value=0.5)
        self.assertEqual(report["plan"]["stance"], "free_only")
        self.assertEqual(report["plan"]["recommendedPaidDraws"], 0)
        self.assertEqual(report["plan"]["recommendedTotalDraws"], 1)
        self.assertEqual(report["mallComparison"]["winner"], "mall")

    def test_thin_edge_recommends_half_bankroll(self):
        # EV 10 元 / 成本 100 积分；point_value 使 ROI 落在 [1.0, 1.2)
        report = evaluate_lottery(self._activity(), point_value=0.095)
        self.assertEqual(report["plan"]["stance"], "buy")
        self.assertEqual(report["plan"]["recommendedPaidDraws"], 5)  # 可负担 10 次的一半

    def test_percentage_style_probabilities_are_normalized(self):
        activity = self._activity()
        activity["prizes"] = [
            {"name": "a", "probability": 30, "value": 10.0},
            {"name": "b", "probability": 70, "value": 0.0},
        ]
        report = evaluate_lottery(activity)
        self.assertAlmostEqual(report["expectedValuePerDraw"], 3.0)

    def test_missing_probabilities_flagged_low_confidence(self):
        activity = self._activity()
        activity["prizes"] = [{"name": "a", "value": 10.0}, {"name": "b", "value": 0.0}]
        report = evaluate_lottery(activity)
        self.assertEqual(report["confidence"], "low")
        self.assertTrue(any("概率" in tip for tip in report["advice"]))

    def test_free_draws_have_no_opportunity_cost(self):
        activity = self._activity()
        activity["userResources"] = {"availablePoints": 0, "remainingDraws": 3, "tickets": 2}
        report = evaluate_lottery(activity, point_value=0.05)
        self.assertEqual(report["resource"]["freeDraws"], 5)
        self.assertEqual(report["plan"]["recommendedPaidDraws"], 0)
        self.assertEqual(report["simulation"]["totalOpportunityCost"], 0.0)
        self.assertEqual(report["simulation"]["lossProbability"], 0.0)

    def test_simulation_is_reproducible(self):
        activity = self._activity()
        activity["userResources"] = {"availablePoints": 10000, "remainingDraws": 0, "tickets": 0}
        first = evaluate_lottery(activity, point_value=0.03)
        second = evaluate_lottery(activity, point_value=0.03)
        self.assertEqual(first["simulation"]["medianNet"], second["simulation"]["medianNet"])
        self.assertEqual(
            first["simulation"]["lossProbability"], second["simulation"]["lossProbability"]
        )

    def test_stress_scenario_reported_when_bankroll_larger(self):
        activity = self._activity()
        activity["userResources"] = {"availablePoints": 10000, "remainingDraws": 0, "tickets": 0}
        report = evaluate_lottery(activity, point_value=0.5)
        # ROI 仅 0.2，付费次数为 0，因此推荐方案无样本，但全额投入情景必须给出回测
        self.assertEqual(report["plan"]["recommendedTotalDraws"], 0)
        self.assertIsNotNone(report["stressSimulation"])
        self.assertEqual(report["stressSimulation"]["drawsPerTrial"], 100)
        self.assertGreater(report["stressSimulation"]["lossProbability"], 0.5)

    def test_empty_prize_list_is_handled(self):
        report = evaluate_lottery({"activityName": "空"})
        self.assertEqual(report["confidence"], "low")
        self.assertIn("note", report)

    def test_zero_cost_lottery_is_strong_buy(self):
        activity = self._activity()
        activity["costPerDraw"] = {"points": 0}
        activity["userResources"] = {"availablePoints": 500, "remainingDraws": 2, "tickets": 0}
        report = evaluate_lottery(activity, point_value=0.05)
        self.assertEqual(report["plan"]["stance"], "strong_buy")


if __name__ == "__main__":
    unittest.main(verbosity=2)
