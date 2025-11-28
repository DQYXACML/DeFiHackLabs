# V2.5约束提取器 - 防火墙配置集成使用指南

## 快速开始

### 单个协议提取

```bash
cd /home/dqy/Firewall/FirewallOnchain/DeFiHackLabs

# 基础用法（使用防火墙配置）
python3 extract_param_state_constraints_v2_5.py \
  --protocol BarleyFinance_exp \
  --year-month 2024-01 \
  --use-firewall-config
```

### 批量提取

```bash
# 处理2024-01的所有协议
python3 extract_param_state_constraints_v2_5.py \
  --batch \
  --filter 2024-01 \
  --use-firewall-config
```

## 工作原理

### 三层分析目标选择策略

```
1. 防火墙配置优先
   ├─ 读取 constraint_rules_v2.json
   ├─ 提取 vulnerable_contract.address
   └─ 检查该合约是否有状态变化
        ├─ 有变化 → 使用该合约 ✓
        └─ 无变化 → 进入下一层

2. 动态检测回退
   ├─ 分析 attack_state.json 和 attack_state_after.json
   ├─ 对比所有合约的storage
   └─ 找到所有有状态变化的合约

3. 智能选择主目标
   └─ 从有变化的合约中选择变化量最大的
```

### 函数级过滤

如果有防火墙配置，只分析被保护的函数：

```
攻击脚本识别到的函数: [flash, bond, debond, transfer, approve]
防火墙配置的函数: [flash, bond, debond]
实际分析: [flash, bond, debond]  # 忽略 transfer, approve
```

## 输出说明

### 日志示例

```
[INFO] 开始提取约束 (V2): BarleyFinance_exp
[INFO] 防火墙配置读取器已初始化
[INFO]   被攻击合约: wBARL (0x04c80bb477...)
[INFO]   识别到 3 个函数调用
[INFO]   防火墙配置指定: 1 个合约
[INFO]   使用防火墙配置中有状态变化的合约: 1 个
[INFO]   0x04c80bb477...: 2 个slot变化
[INFO]   使用变化最大的合约作为主要分析目标: 0x04c80bb477... (2 slots)
[INFO]   根据防火墙配置，分析 3/3 个被保护函数
[INFO] 检测到 2 个slot变化
[SUCCESS]   生成约束: 5 个
```

### 关键指标解读

| 日志 | 含义 | 好/坏 |
|-----|------|------|
| `防火墙配置指定: 1 个合约` | 找到了防火墙配置 | ✅ 好 |
| `使用防火墙配置中有状态变化的合约` | 配置的合约确实有变化 | ✅ 好 |
| `回退到动态检测` | 配置的合约无变化，自动切换 | ⚠️ 警告但正常 |
| `根据防火墙配置，分析 3/5 个被保护函数` | 只分析被保护的函数 | ✅ 好 |
| `生成约束: 0 个` | 未生成约束，可能是脚本解析问题 | ❌ 需检查 |

## 常见场景

### 场景1：配置的合约有状态变化（理想情况）

**BarleyFinance_exp**:
```
防火墙配置: wBARL (0x04c80...)
检测结果: 2个slot变化 ✓
使用合约: wBARL
生成约束: 5个 ✓
```

### 场景2：配置的合约无变化（自动回退）

**Freedom_exp**:
```
防火墙配置: FREEB (0xae3ada...)
检测结果: 0个slot变化 ✗
回退策略: 动态检测
发现合约: IERC20 (5 slots), WBNB (2 slots), DPP (3 slots)
使用合约: IERC20 (变化最大)
```

### 场景3：无防火墙配置（纯动态模式）

```bash
# 不使用 --use-firewall-config 参数
python3 extract_param_state_constraints_v2_5.py \
  --protocol NewProtocol_exp \
  --year-month 2024-01
```

行为：直接进入动态检测模式

## 故障排查

### 问题1：生成0个约束

**可能原因**：
1. 攻击脚本解析失败（识别到0个函数调用）
2. 所有合约都没有状态变化
3. attack_state.json 或 attack_state_after.json 缺失

**解决方案**：
```bash
# 检查攻击脚本
cat src/test/2024-01/{Protocol}_exp.sol | grep -E "function|interface"

# 检查状态文件
ls -la extracted_contracts/2024-01/{Protocol}/attack_state*.json

# 查看详细日志
python3 extract_param_state_constraints_v2_5.py \
  --protocol {Protocol}_exp \
  --year-month 2024-01 \
  --use-firewall-config 2>&1 | less
```

### 问题2：防火墙配置未加载

**日志特征**：
```
[WARNING] 无法加载防火墙配置读取器: No module named 'firewall_config_reader'
```

**解决方案**：
```bash
# 确保文件存在
ls -la firewall_config_reader.py

# 检查Python路径
python3 -c "import sys; print(sys.path)"
```

### 问题3：所有合约都无状态变化

**日志特征**：
```
[WARNING] 未检测到任何合约的状态变化
```

**可能原因**：
- attack_state.json 和 attack_state_after.json 内容相同
- 状态采集时区块号错误

**解决方案**：
```bash
# 检查区块号
python3 << 'EOF'
import json
with open('extracted_contracts/2024-01/{Protocol}/attack_state.json') as f:
    before = json.load(f)
with open('extracted_contracts/2024-01/{Protocol}/attack_state_after.json') as f:
    after = json.load(f)
print(f"攻击前区块: {before['metadata']['block_number']}")
print(f"攻击后区块: {after['metadata']['block_number']}")
EOF

# 如果区块号相同，重新采集状态
python3 src/test/collect_attack_states.py \
  --protocol {Protocol}_exp \
  --force
```

## 高级用法

### 只使用V2（不用防火墙配置）

```bash
python3 extract_param_state_constraints_v2_5.py \
  --protocol BarleyFinance_exp \
  --year-month 2024-01
  # 不加 --use-firewall-config
```

### 查看防火墙配置内容

```bash
python3 << 'EOF'
from pathlib import Path
from firewall_config_reader import FirewallConfigReader

reader = FirewallConfigReader(Path.cwd())
config = reader.load_config('BarleyFinance_exp', '2024-01')

if config:
    print(f"协议: {config.protocol}")
    print(f"被保护合约: {len(config.protected_contracts)}")
    for c in config.protected_contracts:
        print(f"  - {c.name}: {c.address}")
    print(f"被保护函数: {len(config.protected_functions)}")
    for f in config.protected_functions:
        print(f"  - {f.function}")
EOF
```

## 性能对比

| 模式 | 协议 | 分析时间 | 约束数 | 质量 |
|-----|------|---------|--------|------|
| 纯V2 | BarleyFinance_exp | ~10s | 5 | 数据驱动 |
| V2+防火墙配置 | BarleyFinance_exp | ~8s | 5 | 数据驱动 |
| 纯V2 | Freedom_exp | ~12s | 2 | 启发式 |
| V2+防火墙配置 | Freedom_exp | ~15s | 0 | - |

**说明**：
- 防火墙配置模式稍慢（多了配置读取和验证）
- 但约束质量更高（减少启发式约束）

## 最佳实践

1. **始终使用 `--use-firewall-config`**
   - 除非明确知道没有防火墙配置

2. **批量处理时启用防火墙配置**
   ```bash
   python3 extract_param_state_constraints_v2_5.py \
     --batch --filter 2024-01 --use-firewall-config
   ```

3. **检查生成的约束质量**
   ```bash
   # 查看约束类型分布
   python3 << 'EOF'
   import json
   from pathlib import Path
   from collections import Counter

   corr_types = Counter()
   for f in Path('extracted_contracts/2024-01').glob('*/constraint_rules_v2.json'):
       with open(f) as fp:
           d = json.load(fp)
       for c in d.get('constraints', []):
           corr_type = c.get('analysis', {}).get('correlation_type', 'unknown')
           corr_types[corr_type] += 1

   for t, count in corr_types.most_common():
       print(f"{t}: {count}")
   EOF
   ```

## 相关文件

- `firewall_config_reader.py` - 防火墙配置读取器
- `extract_param_state_constraints_v2_5.py` - V2.5约束提取器
- `V2_5_FIREWALL_INTEGRATION_REPORT.md` - 详细技术报告
