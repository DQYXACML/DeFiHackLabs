# 动态不变量检测报告 - MIC_exp

**生成时间**: 2025-11-14 04:11:36

---

## 📋 基本信息

- **攻击名称**: MIC_exp
- **年月**: 2024-01
- **检测方法**: 动态执行（Anvil重放）

## 📊 执行摘要

- **总不变量数**: 10
- **违规数量**: 6 ❌
- **通过数量**: 4 ✅
- **违规率**: 60.0%

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
  "totalSupply": 0,
  "reserves": 0,
  "leverage_ratio": "inf",
  "max_allowed_ratio": "1.10"
}
```

---

### 2. [SINV_003] bounded_change_rate

**严重程度**: `HIGH`

**描述**: totalSupply should not change more than 50% in single transaction

**阈值**: `50.0%`
**实际值**: `100.0%` 🚨

**影响**: Flash mint attacks, accounting manipulation, or reentrancy

**证据**:
```json
{
  "contract": "0xafebc0a9e26fea567cc9e6dd7504800c67f4e3fe",
  "slot": 2,
  "value_before": 489982930986835137684486657990555633941558688085,
  "value_after": 0,
  "absolute_change": -489982930986835137684486657990555633941558688085,
  "change_rate": "100.0%"
}
```

---

### 3. [SINV_004] bounded_change_rate

**严重程度**: `HIGH`

**描述**: totalSupply should not change more than 50% in single transaction

**阈值**: `50.0%`
**实际值**: `100.0%` 🚨

**影响**: Flash mint attacks, accounting manipulation, or reentrancy

**证据**:
```json
{
  "contract": "0x92b7807bf19b7dddf89b706143896d05228f3121",
  "slot": 2,
  "value_before": 6276464042267695581365232213172945,
  "value_after": 0,
  "absolute_change": -6276464042267695581365232213172945,
  "change_rate": "100.0%"
}
```

---

### 4. [SINV_007] bounded_change_rate

**严重程度**: `HIGH`

**描述**: totalSupply should not change more than 50% in single transaction

**阈值**: `50.0%`
**实际值**: `100.0%` 🚨

**影响**: Flash mint attacks, accounting manipulation, or reentrancy

**证据**:
```json
{
  "contract": "0xc5f6e6eab516bbdcf9f96043779c3db9de7bf5ef",
  "slot": 2,
  "value_before": 489982930986835137684486657990555633941558688085,
  "value_after": 0,
  "absolute_change": -489982930986835137684486657990555633941558688085,
  "change_rate": "100.0%"
}
```

---

### 5. [SINV_008] bounded_change_rate

**严重程度**: `HIGH`

**描述**: totalSupply should not change more than 50% in single transaction

**阈值**: `50.0%`
**实际值**: `100.0%` 🚨

**影响**: Flash mint attacks, accounting manipulation, or reentrancy

**证据**:
```json
{
  "contract": "0x1864f7cb1ee4f392716713fb8760f9a0d2793a3d",
  "slot": 2,
  "value_before": 489982930986835137684486657990555633941558688085,
  "value_after": 0,
  "absolute_change": -489982930986835137684486657990555633941558688085,
  "change_rate": "100.0%"
}
```

---

### 6. [SINV_009] bounded_change_rate

**严重程度**: `HIGH`

**描述**: totalSupply should not change more than 50% in single transaction

**阈值**: `50.0%`
**实际值**: `100.0%` 🚨

**影响**: Flash mint attacks, accounting manipulation, or reentrancy

**证据**:
```json
{
  "contract": "0xf8fe3df51d109226623419db451bacb3e38adb9a",
  "slot": 2,
  "value_before": 489982930986835137684486657990555633941558688085,
  "value_after": 0,
  "absolute_change": -489982930986835137684486657990555633941558688085,
  "change_rate": "100.0%"
}
```

---

## ✅ 通过检测的不变量

1. **[SINV_001]** share_price_stability - Vault share price must not change more than 5% per transaction
   - 阈值: `5.0%`, 实际: `0.0% (无变化)`

2. **[SINV_005]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `N/A (数据未捕获)`

3. **[SINV_006]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `N/A (数据未捕获)`

4. **[SINV_010]** bounded_change_rate - totalSupply should not change more than 50% in single transaction
   - 阈值: `50.0%`, 实际: `N/A (数据未捕获)`

## 📦 存储变化摘要

- **变化的合约数**: 8
- **变化的存储槽数**: 8

**变化率最大的存储槽**:

- `0xafebc0a9...` slot 2: 489982930986835137684486657990555633941558688085 → 0 (变化 100.00%)
- `0xf8fe3df5...` slot 2: 489982930986835137684486657990555633941558688085 → 0 (变化 100.00%)
- `0x92b7807b...` slot 2: 6276464042267695581365232213172945 → 0 (变化 100.00%)
- `0x1864f7cb...` slot 2: 489982930986835137684486657990555633941558688085 → 0 (变化 100.00%)
- `0xc5f6e6ea...` slot 2: 489982930986835137684486657990555633941558688085 → 0 (变化 100.00%)

---

*报告由动态不变量检测器自动生成*