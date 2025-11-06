# 动态不变量检测报告 - SocketGateway_exp

**生成时间**: 2025-11-05 16:58:42

---

## 📋 基本信息

- **攻击名称**: SocketGateway_exp
- **年月**: 2024-01
- **检测方法**: 动态执行（Anvil重放）

## 📊 执行摘要

- **总不变量数**: 1
- **违规数量**: 0 ❌
- **通过数量**: 1 ✅
- **违规率**: 0.0%

## ✅ 通过检测的不变量

1. **[SINV_001]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `0.0%`

## 📦 存储变化摘要

- **变化的合约数**: 1
- **变化的存储槽数**: 1

---

*报告由动态不变量检测器自动生成*