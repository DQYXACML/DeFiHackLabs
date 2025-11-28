# 回调函数识别优化 - 快速启动指南

## 🚀 一键测试

### 运行批量测试
```bash
# 测试所有2024-01协议 (推荐)
python3 extract_param_state_constraints_v2_5.py \
  --batch \
  --filter 2024-01 \
  --use-firewall-config

# 查看日志
tail -f logs/batch_test_phase12_fixed.log
```

### 测试单个协议
```bash
# 测试Gamma_exp (13个约束, 5个回调)
python3 extract_param_state_constraints_v2_5.py \
  --protocol Gamma_exp \
  --year-month 2024-01 \
  --use-firewall-config

# 测试WiseLending02_exp (22个约束, test_poc入口点)
python3 extract_param_state_constraints_v2_5.py \
  --protocol WiseLending02_exp \
  --year-month 2024-01 \
  --use-firewall-config
```

## 📊 当前状态

| 指标 | 值 | 目标达成 |
|------|-----|---------|
| 成功率 | **89.5%** (17/19) | ✅ 超过80% |
| 总约束数 | **83** | ✅ |
| 失败协议 | 2个 (Bmizapper, RadiantCapital) | ⚠️ 需进一步优化 |

## 🔍 查看结果

### 查看生成的约束
```bash
# 查看单个协议的约束
cat extracted_contracts/2024-01/Gamma_exp/constraint_rules_v2.json | jq '.constraints | length'

# 查看所有协议的约束数量
for dir in extracted_contracts/2024-01/*/; do
  protocol=$(basename "$dir")
  count=$(cat "$dir/constraint_rules_v2.json" 2>/dev/null | jq '.constraints | length' 2>/dev/null || echo "0")
  printf "%-30s %3s 约束\n" "$protocol" "$count"
done | sort -k2 -nr
```

### 验证回调识别
```bash
# 查看Gamma_exp的回调识别日志
grep "识别回调函数" logs/batch_test_phase12_fixed.log | grep Gamma

# 输出示例:
# [DEBUG]   识别回调函数: uniswapV3FlashCallback (协议: uniswap_v3)
# [DEBUG]   识别回调函数: uniswapV3SwapCallback (协议: uniswap_v3)
# [DEBUG]   识别回调函数: algebraSwapCallback (协议: uniswap_v3)
# [DEBUG]   识别回调函数: receiveFlashLoan (协议: balancer)
# [DEBUG]   识别回调函数: receive (协议: fallback)
```

## 🎯 优化亮点

### 1. 回调模式库 (40+模式)
支持的协议类别:
- ✅ DODO/DPP系列
- ✅ Uniswap V2/V3及分叉
- ✅ AAVE闪电贷
- ✅ Balancer闪电贷
- ✅ ERC标准回调 (721, 1155, 777)
- ✅ fallback/receive

### 2. 调用图遍历
- 从多个入口点(testExploit + 回调)开始
- BFS遍历所有可达函数
- 深度限制: max_depth=10

### 3. 灵活入口点
支持的命名模式:
- ✅ `testExploit` (标准)
- ✅ `test_poc` (WiseLending02)
- ✅ `test_*` (通配符)
- ✅ 自动识别回调函数

## 📈 测试案例

### Case 1: Gamma_exp (多回调链)
```bash
python3 extract_param_state_constraints_v2_5.py \
  --protocol Gamma_exp \
  --year-month 2024-01 \
  --use-firewall-config
```

**期望输出**:
```
[DEBUG]   识别回调函数: uniswapV3FlashCallback (协议: uniswap_v3)
[DEBUG]   识别回调函数: uniswapV3SwapCallback (协议: uniswap_v3)
[DEBUG]   识别回调函数: algebraSwapCallback (协议: uniswap_v3)
[DEBUG]   识别回调函数: receiveFlashLoan (协议: balancer)
[DEBUG]   识别回调函数: receive (协议: fallback)
[INFO]   识别到 6 个入口点: ['testExploit', 'uniswapV3FlashCallback', ...]
[INFO]   可达函数: 7/8
[INFO]   收集到 16 个唯一外部调用
[SUCCESS]   生成约束: 13 个 ✅
```

### Case 2: WiseLending02_exp (入口点修复)
```bash
python3 extract_param_state_constraints_v2_5.py \
  --protocol WiseLending02_exp \
  --year-month 2024-01 \
  --use-firewall-config
```

**期望输出**:
```
[DEBUG]   发现 7 个函数: ['setUp', 'test_poc', '_simulateOracleCall', ...]
[INFO]   识别到 1 个入口点: ['test_poc'] ✅
[INFO]   可达函数: 1/7
[INFO]   收集到 13 个唯一外部调用
[SUCCESS]   生成约束: 22 个 ✅
```

## 🐛 已修复的Bug

### Bug #1: contract_name为None
```python
# Before: AttributeError when contract_name is None
if self.protocol_dir and contract_name.lower() in ...:

# After: Added null check
if self.protocol_dir and contract_name:
    if contract_name.lower() in ...:
```

### Bug #2: slot_changes未定义
```python
# Before: UnboundLocalError
for c in slot_changes[:5]  # slot_changes may not be defined

# After: Explicit extraction
primary_slot_changes = all_slot_changes.get(primary_address, [])
for c in primary_slot_changes[:5]
```

## ⚠️ 已知限制

### 失败的协议 (2个)

1. **Bmizapper_exp**: 目标合约无状态变化
   - 原因: 状态变化在外部合约(USDC)
   - 解决方案: 实现跨合约约束生成

2. **RadiantCapital_exp**: 无状态变化记录
   - 原因: 状态快照收集不完整
   - 解决方案: 改进CollectAttackData脚本

## 📚 文档

- **完整报告**: `CALLBACK_OPTIMIZATION_FINAL_REPORT.md`
- **执行摘要**: `CALLBACK_OPTIMIZATION_SUMMARY.md`
- **本文档**: `CALLBACK_OPTIMIZATION_README.md`

## 🔧 故障排查

### 问题: 没有识别到回调函数
```bash
# 检查日志
grep "识别回调函数" logs/batch_test_phase12_fixed.log

# 如果没有输出，检查脚本是否包含回调函数
grep -E "(DPPFlashLoanCall|uniswapV3FlashCallback|receiveFlashLoan)" \
  src/test/2024-01/YourProtocol_exp.sol
```

### 问题: 入口点未找到
```bash
# 检查测试函数名
grep "function test" src/test/2024-01/YourProtocol_exp.sol

# 支持的命名:
# - testExploit (标准)
# - test_poc (WiseLending02)
# - test_* (任意test开头的函数)
```

### 问题: 生成约束为0
```bash
# 检查状态变化
cat extracted_contracts/2024-01/YourProtocol_exp/attack_state.json | \
  jq '.addresses | to_entries | map(select(.value.storage | length > 0))'

# 如果状态为空，需要重新收集攻击状态
```

## 💡 性能提示

### 并行批量测试 (未来优化)
```bash
# 当前: 串行处理 (~120秒/19协议)
python3 extract_param_state_constraints_v2_5.py --batch

# 未来: 并行处理 (预期 ~40秒)
# (需要实现多进程支持)
```

### 缓存机制
系统已实现函数发现和调用图的缓存:
```python
self._functions_cache: List[FunctionInfo] = None
self._call_graph_cache: Dict[str, List[str]] = None
```

## 📊 统计数据

### 代码变更
- 新增: +850行
- 修改: +50行
- 删除: -10行

### 性能影响
- 执行时间: +50% (~5-8秒/协议)
- 约束生成: +538% (13 → 83)
- 成功率: +50.6% (38.9% → 89.5%)

---

**版本**: 1.0 Final
**状态**: ✅ 生产就绪
**维护**: 定期更新回调模式库
