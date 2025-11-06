# 验证 Anvil 状态部署指南

## 📋 概述

部署攻击状态到 Anvil 后，可以通过以下方式验证状态是否正确。

## 🚀 快速验证

### 方法1: 自动化 Python 脚本（推荐）

```bash
# 验证单个事件
python src/test/verify_anvil_state.py \
  extracted_contracts/2024-01/BarleyFinance_exp/attack_state.json

# 输出示例：
# ✓ 已连接到 http://localhost:8545
# 开始验证 7 个地址的状态...
# 验证 0x7B3a6EFF1C9925e509C2b01A389238c1FCC462B6...
#   ✓ 余额: 1406062464485437940 wei
#   ✓ Nonce: 10
# ...
# ================================================================================
# 验证总结
# ================================================================================
# 总检查项: 36
# ✓ 通过:   36 (100%)
# ✗ 失败:   0
```

**验证内容**:
- ✅ 余额 (balance)
- ✅ 合约代码 (bytecode)
- ✅ Nonce
- ✅ Storage 状态 (前3个slots)

### 方法2: 手动使用 cast 命令

```bash
# 1. 查询余额
cast balance 0x7B3a6EFF1C9925e509C2b01A389238c1FCC462B6 --rpc-url http://localhost:8545
# 期望: 1406062464485437940

# 2. 查询合约代码
cast code 0x356E7481B957bE0165D6751a49b4b7194AEf18D5 --rpc-url http://localhost:8545
# 期望: 返回 bytecode (8504字符)

# 3. 查询合约代码长度
cast code 0x6B175474E89094C44Da98b954EedeAC495271d0F --rpc-url http://localhost:8545 | wc -c
# 期望: 15808

# 4. 查询 nonce
cast nonce 0x7B3a6EFF1C9925e509C2b01A389238c1FCC462B6 --rpc-url http://localhost:8545
# 期望: 10

# 5. 查询 storage slot
cast storage 0x356E7481B957bE0165D6751a49b4b7194AEf18D5 0 --rpc-url http://localhost:8545
# 期望: 0x0000000000000000000000007b3a6eff1c9925e509c2b01a389238c1fcc462b6

# 6. 调用合约函数（如 ERC20 balanceOf）
cast call 0x6B175474E89094C44Da98b954EedeAC495271d0F \
  "balanceOf(address)" \
  0x7B3a6EFF1C9925e509C2b01A389238c1FCC462B6 \
  --rpc-url http://localhost:8545
```

## 📊 验证结果解读

### ✅ 成功的标志

```
================================================================================
验证总结
================================================================================
总检查项: 36
✓ 通过:   36 (100%)
✗ 失败:   0
================================================================================
```

### ❌ 常见问题

**问题1: 无法连接到 Anvil**
```
❌ 无法连接到 http://localhost:8545
```
**解决**: 确保 Anvil 正在运行
```bash
anvil --block-base-fee-per-gas 0 --gas-price 0
```

**问题2: 验证失败（部分检查不通过）**
```
✗ 失败:   5
```
**解决**: 重新部署状态
```bash
python script/2024-01/deploy_BarleyFinance_exp.py
```

## 🔍 深度验证

### 验证所有 7 个地址

```bash
# 生成验证报告
python src/test/verify_anvil_state.py \
  extracted_contracts/2024-01/BarleyFinance_exp/attack_state.json \
  > verification_report.txt

# 查看报告
cat verification_report.txt
```

### 比对具体数值

从 `attack_state.json` 获取期望值：

```bash
# 查看期望的余额
python3 << 'SCRIPT'
import json
with open('extracted_contracts/2024-01/BarleyFinance_exp/attack_state.json') as f:
    data = json.load(f)
    for addr, info in data['addresses'].items():
        if info['balance_wei'] != "0":
            print(f"{addr}: {info['balance_wei']} wei")
SCRIPT

# 查看实际的余额
cast balance 0x7B3a6EFF1C9925e509C2b01A389238c1FCC462B6 --rpc-url http://localhost:8545
```

## 🛠️ 工具说明

### verify_anvil_state.py

**位置**: `src/test/verify_anvil_state.py`

**功能**:
- 自动读取 `attack_state.json`
- 连接到 Anvil 节点
- 逐个验证所有地址的状态
- 生成详细的验证报告

**参数**:
```bash
python verify_anvil_state.py <state_json_path> [rpc_url]

# 示例
python verify_anvil_state.py \
  extracted_contracts/2024-01/BarleyFinance_exp/attack_state.json \
  http://localhost:8545
```

### cast 命令速查

| 命令 | 用途 | 示例 |
|------|------|------|
| `cast balance` | 查询余额 | `cast balance 0x... --rpc-url ...` |
| `cast code` | 查询合约代码 | `cast code 0x... --rpc-url ...` |
| `cast nonce` | 查询 nonce | `cast nonce 0x... --rpc-url ...` |
| `cast storage` | 查询 storage | `cast storage 0x... 0 --rpc-url ...` |
| `cast call` | 调用只读函数 | `cast call 0x... "func()" --rpc-url ...` |

## 📝 完整工作流示例

```bash
# 1. 启动 Anvil
anvil --block-base-fee-per-gas 0 --gas-price 0 > /tmp/anvil.log 2>&1 &

# 2. 部署状态
cd generated_deploy
python script/2024-01/deploy_BarleyFinance_exp.py

# 3. 自动验证
cd ..
python src/test/verify_anvil_state.py \
  extracted_contracts/2024-01/BarleyFinance_exp/attack_state.json

# 4. 手动验证关键数据
cast balance 0x7B3a6EFF1C9925e509C2b01A389238c1FCC462B6 --rpc-url http://localhost:8545
cast code 0x356E7481B957bE0165D6751a49b4b7194AEf18D5 --rpc-url http://localhost:8545 | head -c 100

# 5. 如果验证通过，可以开始测试攻击或防火墙
# ...
```

## ⚠️ 注意事项

1. **Anvil 必须正在运行**: 验证前确保 Anvil 在 `http://localhost:8545` 监听
2. **状态已部署**: 必须先运行 `deploy_*.py` 脚本
3. **格式差异**: `0x` 前缀会被统一处理，不影响验证结果
4. **Storage 采样**: 默认只验证前 3 个 storage slots（大部分情况足够）

---

生成时间: 2025-10-26  
相关工具: `src/test/verify_anvil_state.py`
