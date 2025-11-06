# 动态不变量检测报告 - Shell_MEV_0xa898_exp

**生成时间**: 2025-11-05 17:06:14

---

## 📋 基本信息

- **攻击名称**: Shell_MEV_0xa898_exp
- **年月**: 2024-01
- **攻击交易**: `0x9b3aa1f20c3dc7bfb96c660fc829879e939e684beca7b11ba05755d55edfc9b7`
- **检测方法**: 动态执行（Anvil重放）

## 📊 执行摘要

- **总不变量数**: 4
- **违规数量**: 2 ❌
- **通过数量**: 2 ✅
- **违规率**: 50.0%

## ⚡ 运行时指标

- **Gas使用**: 1,928,348
- **调用深度**: 0
- **重入深度**: 0
- **循环迭代**: 0
- **池子利用率**: 0.0%

## ❌ 违规详情

### 1. [SINV_001] share_price_stability

**严重程度**: `CRITICAL`

**描述**: Vault share price must not change more than 5% per transaction

**阈值**: `5.0%`
**实际值**: `inf%` 🚨

**影响**: Allows attacker to mint underpriced shares and drain underlying assets

**证据**:
```json
{
  "totalSupply_before": 489982930986835137684486657990555633941558688085,
  "totalSupply_after": 489982930986835137684486657990555633941558688085,
  "totalSupply_change_pct": "0.0%",
  "reserves_before": 0,
  "reserves_after": 0,
  "reserves_change_pct": "N/A",
  "share_price_before": "0.000000",
  "share_price_after": "0.000000",
  "share_price_change_pct": "inf%"
}
```

---

### 2. [SINV_002] supply_backing_consistency

**严重程度**: `CRITICAL`

**描述**: Total supply must be backed by proportional underlying reserves

**阈值**: `1.10`
**实际值**: `inf` 🚨

**影响**: Indicates phantom shares minted without backing

**证据**:
```json
{
  "totalSupply": 489982930986835137684486657990555633941558688085,
  "reserves": 0,
  "leverage_ratio": "inf",
  "max_allowed_ratio": "1.10"
}
```

---

## ✅ 通过检测的不变量

1. **[SINV_003]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `0.0%`

2. **[SINV_004]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `0.0%`

## 📦 存储变化摘要

- **变化的合约数**: 2
- **变化的存储槽数**: 2

---

*报告由动态不变量检测器自动生成*