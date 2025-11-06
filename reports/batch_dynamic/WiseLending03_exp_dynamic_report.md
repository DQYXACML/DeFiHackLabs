# 动态不变量检测报告 - WiseLending03_exp

**生成时间**: 2025-11-05 16:58:42

---

## 📋 基本信息

- **攻击名称**: WiseLending03_exp
- **年月**: 2024-01
- **检测方法**: 动态执行（Anvil重放）

## 📊 执行摘要

- **总不变量数**: 14
- **违规数量**: 2 ❌
- **通过数量**: 12 ✅
- **违规率**: 14.3%

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
  "totalSupply_before": 726330175714135941764069406682033110407748398240,
  "totalSupply_after": 726330175714135941764069406682033110407748398240,
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
  "totalSupply": 726330175714135941764069406682033110407748398240,
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

3. **[SINV_005]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `0.0%`

4. **[SINV_006]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `0.0%`

5. **[SINV_007]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `0.0%`

6. **[SINV_008]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `0.0%`

7. **[SINV_009]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `0.0%`

8. **[SINV_010]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `0.0%`

9. **[SINV_011]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `0.0%`

10. **[SINV_012]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `0.0%`

11. **[SINV_013]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `0.0%`

12. **[SINV_014]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `0.0%`

## 📦 存储变化摘要

- **变化的合约数**: 12
- **变化的存储槽数**: 12

---

*报告由动态不变量检测器自动生成*