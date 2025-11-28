# 解决v2.0受限问题 - 完整方案

## 📋 问题总结

v2.0系统在实际数据上无法充分发挥作用,原因:

1. **数据格式限制**: 只有单点状态快照,缺少 before/after 对比
2. **槽位识别困难**: 大量槽位是keccak256哈希(映射),难以识别语义
3. **模板匹配失败**: 无法从数字槽位中找到 "totalSupply", "reserve" 等语义槽位

## 🎯 三种解决方案

### 方案1: 扩展数据收集 ⭐⭐⭐⭐⭐ (推荐)

**描述**: 修改数据收集脚本,收集攻击前后的状态对比

**优点**:
- ✅ 完全发挥v2.0全部功能
- ✅ 可以检测攻击模式
- ✅ 生成针对性防御不变量

**实施步骤**:

#### 1. 扩展attack_state.json格式

**当前格式**:
```json
{
  "metadata": {"block_number": 19106654},
  "addresses": {
    "0x356e74...": {"storage": {"0": "0x...", "1": "0x..."}}
  }
}
```

**新格式**:
```json
{
  "metadata": {
    "attack_block": 19106654,
    "before_block": 19106653  // 攻击前一个区块
  },
  "before_state": {
    "addresses": {
      "0x356e74...": {"storage": {"0": "0x...", "1": "0x..."}}
    }
  },
  "after_state": {
    "addresses": {
      "0x356e74...": {"storage": {"0": "0xNEW", "1": "0xNEW2"}}
    }
  },
  "diff": {  // 自动计算的差异
    "changed_contracts": 3,
    "changed_slots": 15
  }
}
```

#### 2. 修改数据收集脚本

在 `scripts/tools/` 或数据收集脚本中添加:

```python
def collect_attack_state_with_diff(tx_hash: str, chain: str) -> Dict:
    """
    收集攻击前后状态对比

    Args:
        tx_hash: 攻击交易哈希
        chain: 链名称

    Returns:
        包含before/after状态的字典
    """
    # 1. 获取攻击交易所在区块
    tx = web3.eth.get_transaction(tx_hash)
    attack_block = tx['blockNumber']

    # 2. 收集攻击前状态 (区块 N-1)
    before_state = collect_state(attack_block - 1, involved_addresses)

    # 3. 收集攻击后状态 (区块 N)
    after_state = collect_state(attack_block, involved_addresses)

    # 4. 计算差异
    diff = calculate_diff(before_state, after_state)

    return {
        "metadata": {
            "attack_block": attack_block,
            "before_block": attack_block - 1,
            "tx_hash": tx_hash,
            "chain": chain
        },
        "before_state": before_state,
        "after_state": after_state,
        "diff": diff
    }
```

#### 3. v2.0适配新格式

修改 `InvariantGeneratorV2._analyze_state_diff()`:

```python
def _analyze_state_diff(self, attack_state: Dict, semantic_mapping: Dict):
    """分析状态差异(新格式)"""

    # 检查数据格式
    if "before_state" in attack_state and "after_state" in attack_state:
        # 新格式:直接使用
        before = attack_state["before_state"]["addresses"]
        after = attack_state["after_state"]["addresses"]
    else:
        # 旧格式:单点状态,跳过差异分析
        self.logger.warning("单点状态格式,跳过差异分析")
        return None

    # 构建ContractState对象
    before_states = {addr: ContractState(...) for addr in before}
    after_states = {addr: ContractState(...) for addr in after}

    # 计算差异
    return self.diff_calculator.compute_comprehensive_diff(
        before=before_states,
        after=after_states,
        semantic_mapping=semantic_mapping
    )
```

**成本**: 中等(需要修改数据收集脚本)
**收益**: 高(完全启用v2.0功能)

---

### 方案2: 增强槽位识别 ⭐⭐⭐⭐ (折中)

**描述**: 结合ABI和源码,精确识别槽位语义

**优点**:
- ✅ 在单点状态下也能生成有意义的不变量
- ✅ 无需修改数据收集
- ✅ 提高槽位语义识别率从1% → 60%+

**实施步骤**:

#### 1. 从ABI推断槽位布局

```python
class ABIBasedLayoutInference:
    """从ABI推断存储布局"""

    def infer_layout_from_abi(self, abi: List[Dict]) -> Dict[str, int]:
        """
        根据Solidity存储规则推断槽位

        标准ERC20:
        - slot 0: name (string, 2 slots)
        - slot 2: symbol (string, 2 slots)
        - slot 4: decimals (uint8, 1 byte)
        - slot 4: totalSupply (uint256, packed)
        - slot 5: balances (mapping)
        - slot 6: allowances (mapping(address => mapping))
        """
        layout = {}
        current_slot = 0

        # 解析状态变量(需要源码或metadata)
        # 如果只有ABI,使用启发式规则
        if self._has_function(abi, 'totalSupply'):
            layout['totalSupply'] = 2  # ERC20标准
            layout['balances'] = 3

        if self._has_function(abi, 'reserve0'):
            layout['reserve0'] = 8  # UniswapV2标准
            layout['reserve1'] = 9

        return layout
```

#### 2. 从metadata.json提取存储布局

如果有compiler metadata:

```python
def extract_layout_from_metadata(metadata_path: Path) -> Dict:
    """从编译器metadata提取存储布局"""
    with open(metadata_path) as f:
        metadata = json.load(f)

    # Solidity编译器会在metadata中包含存储布局
    if 'storageLayout' in metadata:
        return metadata['storageLayout']['storage']

    return {}
```

#### 3. 改进槽位匹配逻辑

```python
def match_slots_to_template(
    self,
    template: InvariantTemplate,
    inferred_layout: Dict[str, int],  # 从ABI推断的布局
    slot_details: Dict  # 实际槽位数据
) -> Optional[Dict]:
    """
    匹配槽位到模板

    Args:
        template: 不变量模板
        inferred_layout: {"totalSupply": 2, "reserve0": 8, ...}
        slot_details: 实际槽位值

    Returns:
        匹配的槽位映射
    """
    matched = {}

    for required_semantic in template.required_slots:
        # 查找对应槽位号
        if required_semantic in inferred_layout:
            slot_num = str(inferred_layout[required_semantic])

            # 检查该槽位是否存在
            for address, slots in slot_details.items():
                for slot_info in slots:
                    if slot_info['slot'] == slot_num:
                        matched[address] = {
                            slot_num: {
                                "semantic": required_semantic,
                                "value": slot_info['value']
                            }
                        }
                        break

    return matched if matched else None
```

**成本**: 中等(需要增强槽位识别逻辑)
**收益**: 中高(显著提高不变量生成率)

---

### 方案3: 混合v1.0+v2.0 ⭐⭐⭐ (快速)

**描述**: 结合v1.0的槽位关系分析 + v2.0的协议检测和模板

**优点**:
- ✅ 快速实施,无需大改
- ✅ 利用两者优势
- ✅ 立即可用

**实施**:

```python
class HybridInvariantGenerator:
    """混合生成器"""

    def generate(self, project_dir: Path) -> List:
        invariants = []

        # 1. v2.0: 协议检测
        protocol_type = self.v2_detector.detect(...)

        # 2. v2.0: 获取协议模板
        templates = self.v2_templates.get_templates_for_protocol(protocol_type)

        # 3. v1.0: 槽位关系分析
        slot_relations = self.v1_analyzer.find_slot_relationships(...)

        # 4. 融合: 用v1的槽位关系填充v2的模板
        for template in templates:
            for relation in slot_relations:
                if self._matches(template, relation):
                    inv = self._create_invariant(template, relation)
                    invariants.append(inv)

        # 5. v1.0: 通用不变量
        generic_invariants = self.v1_generator.generate_generic(...)
        invariants.extend(generic_invariants)

        return invariants
```

**成本**: 低(主要是整合代码)
**收益**: 中(快速得到可用结果)

---

## 📊 方案对比

| 维度 | 方案1:扩展数据 | 方案2:增强识别 | 方案3:混合 |
|------|---------------|---------------|-----------|
| 实施难度 | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ |
| 开发成本 | 中 | 中-高 | 低 |
| 不变量质量 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| 不变量数量 | 30-50+ | 20-30 | 15-25 |
| 攻击模式检测 | ✅ | ❌ | ❌ |
| 可维护性 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ |

## 🚀 推荐实施顺序

### 短期(1周)
✅ **方案3: 混合v1+v2** - 立即可用
→ 快速产出结果,验证系统价值

### 中期(2-3周)
✅ **方案2: 增强槽位识别** - 提高质量
→ 从ABI/metadata推断布局
→ 改进槽位匹配算法

### 长期(1个月)
✅ **方案1: 扩展数据收集** - 完整功能
→ 收集before/after状态
→ 启用攻击模式检测
→ 生成防御性不变量

---

## 💡 立即可用的改进

即使不实施完整方案,也可以立即改进:

###1. 使用addresses.json识别关键合约

```python
# addresses.json包含了合约角色信息
{
  "Attacker": "0x7b3a6e...",
  "Attack_Contract": "0x356e74...",
  "Vulnerable_Contract": "0x04c80B...",  # 重点关注
  "DAI": "0x6B1754...",
  "BARL": "0x3e2324..."
}
```

重点分析 `Vulnerable_Contract` 的槽位变化。

### 2. 利用ERC20标准槽位

对于ERC20代币,直接使用标准布局:
- Slot 2 = totalSupply
- Slot 3 = balanceOf mapping base

### 3. 生成保守不变量

即使无法精确识别,也可以生成:
```solidity
// 任何槽位的变化率不应超过1000%
invariant slot_X_bounded_change:
    abs(after - before) / before <= 10.0
```

---

## 📝 总结

**当前状态**: v2.0系统完整实现,但受数据格式限制

**推荐路径**:
1. **立即**: 实施方案3(混合),快速产出
2. **近期**: 实施方案2(增强),提高质量
3. **未来**: 实施方案1(完整),最大价值

**预期效果**:
- 方案3: 从0个 → 15-25个不变量
- 方案2: 从15个 → 30-40个不变量
- 方案1: 从30个 → 50+个高质量不变量

所有方案都是渐进式的,可以逐步实施,每步都有价值产出。
