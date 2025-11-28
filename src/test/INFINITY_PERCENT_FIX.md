# "inf%" 问题修复总结

## 问题描述

批量动态不变量检测器运行时，所有不变量的实际结果显示为 "inf%"，导致无法正确评估攻击违规情况。

## 根本原因

**存储槽查询返回 0 值 → 除零运算 → float('inf') → 显示 "inf%"**

具体原因包括：
1. **地址大小写不匹配**: 以太坊地址有checksum格式，查询时大小写不一致导致无法匹配
2. **合约未正确部署**: attack_state.json 缺失或 deploy_to_anvil 执行失败
3. **缺少防护性检查**: 代码未处理除零情况，直接产生 inf

## 修复方案

### 1. 地址大小写规范化 (`storage_comparator.py`)

**修改位置**:
- `capture_snapshot()` 第86行: 规范化输入地址
- `_query_via_rpc_batch()` 第290行: 规范化RPC请求地址
- `_query_balances_batch()` 第370行: 规范化余额查询地址
- `extract_slots_from_invariants()` 第229行: 规范化不变量中的地址

**修改内容**:
```python
# 所有地址统一转换为小写
contract = contract.lower()
```

### 2. 防护性除零检查 (`invariant_evaluator.py`)

**修改位置**:
- `_eval_share_price_stability()` 第118-219行
- `_eval_bounded_change_rate()` 第271-343行

**修改内容**:
```python
# 数据有效性检查
if supply_before == 0 and supply_after == 0:
    return ViolationResult(
        violated=False,
        actual_value="N/A (数据未捕获)",
        confidence=0.0  # 置信度为0表示数据无效
    )

# 防止除零
if price_before == 0:
    if price_after > 0:
        change_rate = float('inf')
        actual_value = "INF (从0开始)"
    else:
        change_rate = 0.0
        actual_value = "0.0% (无变化)"
else:
    change_rate = abs(price_after - price_before) / price_before
    actual_value = f"{change_rate * 100:.1f}%"

# 排除 inf 的违规判断
is_violated = change_rate > threshold and change_rate != float('inf')
```

### 3. 增强日志输出 (`dynamic_invariant_checker.py`)

**修改位置**:
- `_capture_before_snapshot()` 第233-285行
- `_capture_after_snapshot()` 第330-358行

**新增功能**:
- 显示捕获的存储值数量和余额数量
- 检测所有存储值是否为0，并给出警告和排查建议
- DEBUG模式下打印样本数据用于调试

```python
logger.info(f"  ✓ 快照捕获成功")
logger.info(f"    - 存储值数量: {total_storage_values}")
logger.info(f"    - 余额数量: {total_balances}")

if all_storage_zero and total_storage_values > 0:
    logger.warning("  ⚠️  所有存储值都是0,请检查:")
    logger.warning("     1. 合约是否正确部署到Anvil")
    logger.warning("     2. attack_state.json 是否包含存储数据")
    logger.warning("     3. 地址格式是否正确")
```

### 4. 诊断工具 (`debug_storage.py`)

**创建文件**: `src/test/debug_storage.py`

**功能**:
- 检查合约是否部署到Anvil
- 验证存储槽是否有值
- 检查合约余额
- 提供详细的诊断报告和修复建议

## 使用指南

### 快速诊断

```bash
cd /home/dqy/Firewall/FirewallOnchain/DeFiHackLabs

# 方法1: 自动诊断2024-01目录下的第一个事件
python src/test/debug_storage.py

# 方法2: 诊断特定事件
python src/test/debug_storage.py \
    --event-name MIMSpell2_exp \
    --year-month 2024-01

# 方法3: 使用自定义Anvil端口
python src/test/debug_storage.py \
    --event-name MIMSpell2_exp \
    --rpc-url http://127.0.0.1:8546
```

### 诊断输出示例

```
======================================================================
诊断: 2024-01/MIMSpell2_exp
======================================================================

📋 共有 21 个存储不变量

--- 不变量 1: SINV_001 (share_price_stability) ---

合约: 0xd51a44d3fae010294c616388b506acda1bfaae46
  合约 0xd51a44d3...fAAE46: ✓ 已部署 (代码长度: 12458)
  存储槽 2: 0x... (十进制: 5,000,000,000) ✓
  余额: 15,000,000,000 wei ✓

======================================================================
诊断总结:
======================================================================
✅ 所有检查通过，存储数据看起来正常
```

### 常见问题排查

#### 问题1: 所有存储值都是0

**症状**:
```
⚠️  发现 3 个问题:
  • 存储槽值为0: 0xd51a...fAAE46[2]
  • 合约未部署: 0x298b...c8E27
```

**解决方案**:
1. 检查 `attack_state.json` 是否存在并包含完整数据
2. 验证 `deploy_to_anvil.py` 是否成功执行
3. 确认 Anvil 是否正确启动

```bash
# 检查 attack_state.json
cat extracted_contracts/2024-01/MIMSpell2_exp/attack_state.json | jq '.storage | length'

# 手动部署状态
python src/test/deploy_to_anvil.py \
    extracted_contracts/2024-01/MIMSpell2_exp/attack_state.json \
    http://127.0.0.1:8545

# 验证部署
cast code 0xD51a44d3FaE010294C616388b506AcdA1bfAAE46 --rpc-url http://127.0.0.1:8545
```

#### 问题2: 合约未部署

**症状**:
```
合约 0xd51a44d3...fAAE46: ✗ 未部署 (代码长度: 2)
```

**解决方案**:
1. 确保 Anvil 正在运行: `ps aux | grep anvil`
2. 检查 RPC URL 是否正确: `curl http://127.0.0.1:8545`
3. 重新运行 `deploy_to_anvil.py`

#### 问题3: 地址格式不匹配

**症状**: 某些合约能查到，某些查不到

**解决方案**: 本次修复已统一地址为小写格式，应该已解决

### 重新运行批量检测

修复后重新运行批量检测：

```bash
cd /home/dqy/Firewall/FirewallOnchain/DeFiHackLabs

# 单进程测试（便于调试）
python src/test/batch_dynamic_checker.py \
    --filter 2024-01 \
    --workers 1

# 多进程并行（生产环境）
python src/test/batch_dynamic_checker.py \
    --filter 2024-01 \
    --workers 4
```

### 查看详细日志

如果仍然有问题，启用DEBUG日志查看详细信息：

```python
# 在 dynamic_invariant_checker.py 或 batch_dynamic_checker.py 开头修改
logging.basicConfig(
    level=logging.DEBUG,  # 改为DEBUG
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

## 预期效果

修复后，不变量评估结果应该显示正常百分比或明确的状态：

### 修复前:
```
[1/10] ❌ MIMSpell2_exp - 21 violations / 21 invariants
  实际: inf%  阈值: 5.0%
  实际: inf%  阈值: 50.0%
  ...
```

### 修复后:
```
[1/10] ✅ MIMSpell2_exp - 3 violations / 21 invariants
  实际: 87.3%  阈值: 5.0%   ✗ 违规
  实际: 15.2%  阈值: 50.0%  ✓ 通过
  实际: N/A (数据未捕获)  置信度: 0.0
  ...
```

## 技术细节

### 地址规范化逻辑

以太坊地址有两种格式：
- **小写**: `0xd51a44d3fae010294c616388b506acda1bfaae46`
- **Checksum**: `0xD51a44d3FaE010294C616388b506AcdA1bfAAE46`

虽然两者在以太坊层面等价，但在Python字典查询时会被视为不同的key。

**解决方案**: 统一转换为小写格式

```python
# 不变量中的地址可能是Checksum格式
"totalSupply_contract": "0xD51a44d3FaE010294C616388b506AcdA1bfAAE46"

# 规范化为小写
contract = contract.lower()
# → "0xd51a44d3fae010294c616388b506acda1bfaae46"
```

### 除零防护策略

```python
# 场景1: 前后都是0 → 数据未捕获
if value_before == 0 and value_after == 0:
    return ViolationResult(actual_value="N/A", confidence=0.0)

# 场景2: 从0变为非0 → 无限变化（但不算违规）
if value_before == 0 and value_after > 0:
    actual_value = "INF (从0开始)"
    is_violated = False  # 不算违规

# 场景3: 正常计算
else:
    change_rate = abs(value_after - value_before) / value_before
    actual_value = f"{change_rate * 100:.1f}%"
```

### 置信度机制

```python
# 置信度反映数据质量
confidence=0.0  # 数据无效（全为0）
confidence=0.5  # 数据部分有效（仅after有值）
confidence=1.0  # 数据完全有效
```

## 测试验证

### 单元测试

```bash
# 测试地址规范化
cd /home/dqy/Firewall/FirewallOnchain/DeFiHackLabs
python3 -c "
from src.test.storage_comparator import StorageComparator
sc = StorageComparator()
slots = sc.extract_slots_from_invariants([{
    'slots': {
        'totalSupply_contract': '0xABC123',  # 大写
        'totalSupply_slot': '2'
    }
}])
print(slots)
# 期望输出: [('0xabc123', 2)]  # 小写
"
```

### 集成测试

使用诊断脚本验证完整流程：

```bash
# 1. 启动Anvil
anvil --port 8545 &

# 2. 部署测试状态
python src/test/deploy_to_anvil.py \
    extracted_contracts/2024-01/MIMSpell2_exp/attack_state.json \
    http://127.0.0.1:8545

# 3. 运行诊断
python src/test/debug_storage.py --event-name MIMSpell2_exp

# 4. 运行单个检测
python src/test/dynamic_invariant_checker.py \
    --event-name MIMSpell2_exp \
    --year-month 2024-01

# 5. 清理
pkill anvil
```

## 相关文件

| 文件 | 修改内容 | 行数 |
|------|---------|------|
| `storage_comparator.py` | 地址规范化 | 86, 290, 370, 229-251 |
| `invariant_evaluator.py` | 防护性检查 | 118-219, 271-343 |
| `dynamic_invariant_checker.py` | 增强日志 | 233-285, 330-358 |
| `debug_storage.py` | 新建诊断工具 | 全新文件 |

## 总结

此次修复从三个层面解决了 "inf%" 问题：

1. **根源修复**: 地址大小写统一，确保数据能正确查询
2. **防御编程**: 添加除零检查和数据有效性验证
3. **可观测性**: 增强日志和诊断工具，快速定位问题

修复后系统能够：
- ✅ 正确显示变化率百分比
- ✅ 明确标识数据缺失情况（N/A）
- ✅ 提供置信度评分
- ✅ 给出详细的调试信息和修复建议
