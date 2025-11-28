# batch_generate_invariants_v2.py 修改记录

## 修改日期
2025-11-23

## 修改概述
修复了不变量生成脚本中的两个关键问题：
1. **硬编码阈值问题**：所有不变量都使用固定的 `threshold=0.05` 和相同的公式
2. **重复ID问题**：同类型的不变量生成相同的ID（如多个 `PATTERN_flash_change_001`）

## 修改文件
`src/test/invariant_toolkit/invariant_generation/complex_formula_builder.py`

---

## 问题一：硬编码阈值

### 问题描述
原代码中 `_create_pattern_based_invariant()` 方法硬编码了阈值和公式：
```python
# 原代码 (第254-255行)
formula=f"abs(value_after - value_before) / value_before <= 0.05",
threshold=0.05,  # 降低到5%
```

导致所有生成的不变量都是：
```json
{
  "formula": "abs(value_after - value_before) / value_before <= 0.05",
  "threshold": 0.05
}
```

### 解决方案

#### 1. 添加导入 (第9-10行)
```python
import re
from typing import Dict, List, Optional, Set, Tuple
```

#### 2. 新增 `_extract_change_rate_from_evidence()` 方法 (第255-282行)
从 evidence 列表中解析实际变化率：
```python
def _extract_change_rate_from_evidence(self, evidence: List[str]) -> float:
    """
    从evidence列表中提取最大变化率

    Evidence格式示例:
    - "Slot 8: 1234x change"
    - "Slot 9: +156.78%"
    """
    max_rate = 0.0
    for ev in evidence:
        # 匹配 "NNNx change" 格式
        match_x = re.search(r'(\d+(?:\.\d+)?)\s*x\s*change', ev, re.IGNORECASE)
        if match_x:
            rate = float(match_x.group(1))
            max_rate = max(max_rate, rate)
            continue
        # 匹配百分比格式
        match_pct = re.search(r'[+-]?(\d+(?:\.\d+)?)\s*%', ev)
        if match_pct:
            rate = float(match_pct.group(1)) / 100.0
            max_rate = max(max_rate, rate)
    return max_rate if max_rate > 0 else 0.0
```

#### 3. 新增 `_calculate_dynamic_threshold()` 方法 (第284-326行)
基于实际变化率动态计算阈值：
```python
def _calculate_dynamic_threshold(self, pattern, protocol_type) -> Tuple[float, str]:
    actual_change_rate = self._extract_change_rate_from_evidence(pattern.evidence)

    if actual_change_rate <= 0:
        return self._get_default_threshold_for_protocol(protocol_type, pattern.pattern_type.value)

    # 动态计算策略
    if actual_change_rate >= 10.0:  # 1000%+ 变化 (闪电贷特征)
        threshold = max(0.5, actual_change_rate * 0.1)  # 最低50%, 最高500%
        threshold = min(threshold, 5.0)
    elif actual_change_rate >= 1.0:  # 100%-1000% 变化
        threshold = max(0.2, actual_change_rate * 0.5)  # 最低20%, 最高200%
        threshold = min(threshold, 2.0)
    else:  # <100% 变化
        threshold = max(0.05, actual_change_rate * 0.8)  # 最低5%, 最高50%
        threshold = min(threshold, 0.5)

    threshold = round(threshold, 2)
    formula = f"abs(value_after - value_before) / value_before <= {threshold}"
    return threshold, formula
```

#### 4. 新增 `_get_default_threshold_for_protocol()` 方法 (第328-373行)
根据协议类型提供不同的默认阈值：
```python
protocol_defaults = {
    ProtocolType.LENDING: 0.1,          # 借贷协议: 10%
    ProtocolType.AMM: 0.3,              # AMM: 30%
    ProtocolType.VAULT: 0.15,           # Vault: 15%
    ProtocolType.STAKING: 0.2,          # 质押: 20%
    ProtocolType.BRIDGE: 0.05,          # 跨链桥: 5%
    ProtocolType.ERC20: 0.5,            # 代币: 50%
    ProtocolType.GOVERNANCE: 0.1,       # 治理: 10%
    ProtocolType.NFT_MARKETPLACE: 0.3,  # NFT市场: 30%
    ProtocolType.UNKNOWN: 0.2,          # 未知: 20%
}

pattern_adjustments = {
    "flash_change": 0.5,        # 闪电贷: 降低阈值
    "flash_mint": 0.3,
    "price_manipulation": 0.7,
    "ratio_break": 0.6,
    "monotonic_increase": 0.8,
    "reentrancy_balance": 0.5,
    "massive_transfer": 0.4,
}
```

#### 5. 扩展 `_create_pattern_based_invariant()` 方法
支持更多攻击模式类型：

| 模式类型 | 不变量类型 | 公式模板 |
|---------|-----------|---------|
| flash_change | flash_change_prevention | `abs(value_after - value_before) / value_before <= {threshold}` |
| ratio_break | ratio_stability | `abs(ratio_after - ratio_before) / ratio_before <= {threshold}` |
| monotonic_increase | growth_rate_limit | `(value_after - value_before) / value_before <= {threshold}` |
| reentrancy_balance | balance_change_limit | `abs(balance_after - balance_before) / balance_before <= {threshold}` |
| zero_value_change | initialization_limit | `value_after <= {max} when value_before == 0` |
| massive_transfer | transfer_limit | `transfer_amount / total_supply <= {threshold}` |
| price_manipulation | price_change_limit | `abs(price_after - price_before) / price_before <= {threshold}` |
| ownership_change | ownership_protection | `owner_after == owner_before OR authorized_change` |

#### 6. 修改 `_build_slots_dict_from_pattern()` 方法签名
添加 threshold 参数，使用动态阈值：
```python
# 原代码
def _build_slots_dict_from_pattern(self, pattern: ChangePattern) -> Dict:
    # ...
    "threshold": 0.05,  # 硬编码

# 修改后
def _build_slots_dict_from_pattern(self, pattern: ChangePattern, threshold: float = 0.05) -> Dict:
    # ...
    "threshold": threshold,  # 使用动态阈值
```

### 修改效果对比

**修改前**：
```json
{
  "formula": "abs(value_after - value_before) / value_before <= 0.05",
  "threshold": 0.05
}
```

**修改后**（以 NORMIE_exp 为例）：
```json
// 不同不变量有不同阈值
{"threshold": 0.25},  // reentrancy_balance
{"threshold": 0.3},   // ratio_break
{"threshold": 1.3},   // flash_change
{"threshold": 1.33},  // monotonic_increase
{"threshold": 5.0}    // 极端变化
```

---

## 问题二：重复ID

### 问题描述
当同一种攻击模式在多个合约上被检测到时，生成的不变量ID相同：
```json
[
  {"id": "PATTERN_flash_change_001", "contracts": ["0x04c80Bb47..."]},
  {"id": "PATTERN_flash_change_001", "contracts": ["0xC02aaA39..."]}  // 重复!
]
```

### 解决方案

#### 1. 在 `__init__` 中添加ID计数器 (第63-66行)
```python
def __init__(self):
    self.logger = logging.getLogger(__name__ + '.ComplexInvariantGenerator')
    self.cross_contract_analyzer = CrossContractAnalyzer()
    self._pattern_id_counters = {}  # 用于生成唯一ID
```

#### 2. 在 `_generate_from_patterns()` 开始时重置计数器 (第224-226行)
```python
def _generate_from_patterns(self, patterns, storage_layout, protocol_type):
    invariants = []
    self._pattern_id_counters = {}  # 重置ID计数器
    # ...
```

#### 3. 新增 `_get_next_pattern_id()` 方法 (第237-253行)
```python
def _get_next_pattern_id(self, pattern_type: str) -> str:
    """为指定模式类型生成下一个唯一ID"""
    if pattern_type not in self._pattern_id_counters:
        self._pattern_id_counters[pattern_type] = 0

    self._pattern_id_counters[pattern_type] += 1
    counter = self._pattern_id_counters[pattern_type]

    return f"PATTERN_{pattern_type}_{counter:03d}"
```

#### 4. 修改 `_create_pattern_based_invariant()` 使用唯一ID
```python
def _create_pattern_based_invariant(self, pattern, protocol_type):
    pattern_type = pattern.pattern_type.value
    unique_id = self._get_next_pattern_id(pattern_type)  # 生成唯一ID
    # ...
    return ComplexInvariant(
        id=unique_id,  # 使用唯一ID而非 f"PATTERN_{pattern_type}_001"
        # ...
    )
```

### 修改效果对比

**修改前**：
```json
[
  {"id": "PATTERN_flash_change_001"},
  {"id": "PATTERN_flash_change_001"}  // 重复
]
```

**修改后**：
```json
[
  {"id": "PATTERN_flash_change_001"},
  {"id": "PATTERN_flash_change_002"}  // 自动递增
]
```

---

## 验证命令

```bash
# 重新生成某个协议的不变量
rm -f extracted_contracts/2024-01/BarleyFinance_exp/invariants_v2.json
python3 batch_generate_invariants_v2.py --filter "2024-01" --workers 1

# 检查生成结果
cat extracted_contracts/2024-01/BarleyFinance_exp/invariants_v2.json | python3 -c "
import json, sys
data = json.load(sys.stdin)
ids = [inv['id'] for inv in data.get('invariants', [])]
thresholds = set(inv['threshold'] for inv in data.get('invariants', []))
print(f'唯一ID数: {len(set(ids))}/{len(ids)}')
print(f'阈值种类: {sorted(thresholds)}')
"
```

---

## 总结

| 问题 | 原因 | 解决方案 |
|-----|------|---------|
| 阈值固定为0.05 | 硬编码 `threshold=0.05` | 动态计算阈值，基于实际变化率和协议类型 |
| 公式固定 | 只实现了 flash 模式 | 为8种攻击模式实现不同的公式模板 |
| ID重复 | 固定使用 `_001` 后缀 | 添加计数器自动递增 |
