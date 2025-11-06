# 存储级不变量生成 - 快速开始

## 🚀 一键运行（BarleyFinance 例子）

### 前提条件确认
```bash
# ✓ attack_state.json (97KB)
# ✓ barleyfinance_analysis.json (3.6KB)
# 都已存在，可以直接运行！
```

---

## 单条命令完成

```bash
python src/test/generate_invariants_from_monitor.py \
  --monitor-output autopath/barleyfinance_analysis.json \
  --output extracted_contracts/2024-01/BarleyFinance_exp/invariants.json \
  --project BarleyFinance_exp
```

**执行时间：** ~2 秒

**预期输出：**
```
================================================================================
✓ 成功生成 10 个不变量
  - 执行级: 6
  - 存储级: 4
================================================================================
```

---

## 查看结果

### 1. 查看所有存储级不变量
```bash
cat extracted_contracts/2024-01/BarleyFinance_exp/invariants.json | \
  jq '.storage_invariants[] | {id, type, severity}'
```

### 2. 查看关键不变量（股份价格稳定性）
```bash
cat extracted_contracts/2024-01/BarleyFinance_exp/invariants.json | \
  jq '.storage_invariants[0]' | head -30
```

### 3. 查看协议检测结果
```bash
cat extracted_contracts/2024-01/BarleyFinance_exp/invariants.json | \
  jq '.storage_analysis_metadata.protocol_info'
```

---

## 核心输出解读

### SINV_001: 最关键的不变量

```json
{
  "id": "SINV_001",
  "type": "share_price_stability",
  "severity": "critical",
  "formula": "|(reserves/totalSupply)_after - (reserves/totalSupply)_before| / (reserves/totalSupply)_before <= 0.05",
  "violation_impact": "允许攻击者铸造低价股份并耗尽底层资产"
}
```

**含义：**
- Vault 的股份价格（每股对应的底层资产）单次交易变化不能超过 5%
- **这直接检测到了 BarleyFinance 的攻击根因！**

**攻击如何违反此不变量：**
1. 攻击者循环 20 次调用 `flash()` + `bond()`
2. 每次循环铸造新的 wBARL 股份 → `totalSupply ↑`
3. 但底层 BARL 储备金不变 → `reserves` 不变
4. 结果：`reserves / totalSupply` 下降超过 5%
5. → **SINV_001 被违反** → 攻击被检测！

---

## 🎯 与旧方法对比

### 旧方法（执行级不变量）
```json
{
  "type": "loop_iterations",
  "threshold": 10,
  "description": "循环不应超过10次"
}
```
❌ 只知道"有循环"，不知道为什么是攻击

### 新方法（存储级不变量）
```json
{
  "type": "share_price_stability",
  "formula": "|(reserves/totalSupply)_after - ...| <= 0.05",
  "description": "股份价格不应变化超过5%"
}
```
✅ 直接指出"股份价格被操纵" = 攻击根因！

---

## 📝 完整文档

详细步骤、前提条件、故障排查，请查看：
👉 `STORAGE_INVARIANT_USAGE.md`
