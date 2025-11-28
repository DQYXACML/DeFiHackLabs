# 动态不变量检测报告 - Freedom_exp

**生成时间**: 2025-11-14 04:07:02

---

## 📋 基本信息

- **攻击名称**: Freedom_exp
- **年月**: 2024-01
- **检测方法**: 动态执行（Anvil重放）

## 📊 执行摘要

- **总不变量数**: 15
- **违规数量**: 1 ❌
- **通过数量**: 14 ✅
- **违规率**: 6.7%

## ❌ 违规详情

### 1. [SINV_002] supply_backing_consistency

**严重程度**: `CRITICAL`

**描述**: Total supply must be backed by proportional underlying reserves

**阈值**: `1.10`
**实际值**: `inf` 🚨

**影响**: Indicates phantom shares minted without backing

**证据**:
```json
{
  "totalSupply": 1069295261705322660692659746119710186699350608220,
  "reserves": 0,
  "leverage_ratio": "inf",
  "max_allowed_ratio": "1.10"
}
```

---

## ✅ 通过检测的不变量

1. **[SINV_001]** share_price_stability - Vault share price must not change more than 5% per transaction
   - 阈值: `5.0%`, 实际: `0.0%`

2. **[SINV_003]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `0.0%`

3. **[SINV_004]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `0.0%`

4. **[SINV_005]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `N/A (数据未捕获)`

5. **[SINV_006]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `N/A (数据未捕获)`

6. **[SINV_007]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `0.0%`

7. **[SINV_008]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `N/A (数据未捕获)`

8. **[SINV_009]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `N/A (数据未捕获)`

9. **[SINV_010]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `0.0%`

10. **[SINV_011]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `N/A (数据未捕获)`

11. **[SINV_012]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `N/A (数据未捕获)`

12. **[SINV_013]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `0.0%`

13. **[SINV_014]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `N/A (数据未捕获)`

14. **[SINV_015]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `N/A (数据未捕获)`

## 📦 存储变化摘要

- **变化的合约数**: 13
- **变化的存储槽数**: 13

---

*报告由动态不变量检测器自动生成*