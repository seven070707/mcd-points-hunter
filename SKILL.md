---
name: mcd-points-hunter
description: 麦当劳（麦麦）会员积分资产管家。当用户提到麦当劳积分、麦麦积分、积分快过期、积分兑换、麦麦商城、积分抽奖、抽奖值不值、麦麦省、会员权益、积分怎么花划算等问题时使用。可诊断积分到期风险、计算商城商品的每积分价值排序、评估抽奖期望值与投入产出比，并给出可执行的花分方案。
---

# 麦麦积分猎人

把麦当劳积分从「躺着过期」变成「算着花掉」。

## 何时使用本技能

用户出现以下意图时触发：

- 询问麦当劳/麦麦积分的余额、有效期、快过期怎么办
- 问积分该换什么、怎么换最划算
- 问麦麦商城某个商品值不值得兑换
- 问积分抽奖要不要抽、抽几次
- 想盘点自己的会员权益和临期资产

## 工作方式

本技能遵循「**数据获取由 MCP 负责，数值计算由本地引擎负责**」的分工。
不要自己心算或估算任何数字 —— 一律通过 `scripts/points_hunter.py` 计算。

### 第一步：确认时间基准

调用 `now-time-info` 获取当前日期。所有到期倒计时都以它为基准。

### 第二步：采集数据

按需调用以下只读 Tool，把返回的 JSON 原样保存为本地文件：

| 需要什么 | 调用哪个 Tool | 保存为 |
|---|---|---|
| 积分账户与到期明细 | `query-my-account` | `account.json` |
| 商城商品与积分价 | `mall-points-products` | `products.json` |
| 商品权益面值与有效期 | `mall-product-detail` | 合并进 `products.json` |
| 抽奖活动与奖品概率 | `query-lottery-info` | `lottery.json` |
| 已中奖记录 | `query-my-prizes` | 可选，用于券的到期管理 |

### 第三步：交给引擎计算

```bash
# 综合诊断（推荐）
python scripts/points_hunter.py report \
  --account  account.json \
  --products products.json \
  --activity lottery.json

# 单项分析
python scripts/points_hunter.py audit   --account  account.json
python scripts/points_hunter.py mall    --products products.json
python scripts/points_hunter.py lottery --activity lottery.json --point-value 0.0319
```

### 第四步：转述结论

引擎输出的是完整报告。向用户汇报时：

- **先说结论**：最紧急的一件事是什么（通常是「N 天内必须花掉 X 积分」）
- **再给方案**：优先兑换哪件商品、为什么
- **最后给警示**：如果涉及抽奖，明确说出投入产出比与亏损概率
- 保留报告中的关键数字，不要改写成模糊表述

## 关键概念

**每积分价值** = 权益面值(元) ÷ 消耗积分。
商城按积分价排序，会掩盖这个差异；本技能按每积分价值重排。

**积分的真实成本是机会成本**，不是积分个数。
100 积分的机会成本 = 100 × (商城中兑换效率最高商品的每积分价值)。
比较抽奖与商城时，必须用这个口径，否则结论会完全反向。

**蒙特卡洛固定 seed=42**，同一输入必定产出同一结果，可以放心引用。

## 注意事项

- 全程只读，不要调用任何下单、支付、领取类 Tool
- 不传 `--point-value` 时，抽奖模块无法得出真实 ROI，只会输出绝对指标
- 概率缺失或明细缺失时报告会标注 `confidence: low`，转述时必须如实告知用户
- 所有结论仅供参考，积分与商品信息以麦当劳官方渠道为准
