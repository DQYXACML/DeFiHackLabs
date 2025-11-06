# Runtime Invariant Monitor 使用指南

## 📖 简介

这是一个完整的运行时监控系统，用于验证智能合约不变量是否能够检测攻击。

## 🏗️ 系统架构

```
Python验证脚本 (verify_invariants_runtime.py)
    ↓
    ├─→ Anvil (本地测试链)
    ├─→ 状态部署 (deploy_*.py)
    ├─→ Go Monitor (分析交易)
    │    ├─→ Trace Analyzer
    │    ├─→ Data Extractor
    │    └─→ Invariant Evaluator
    └─→ Forge Test (执行攻击)
```

## 🚀 快速开始

### 前置要求

1. **Go 1.21+**
   ```bash
   go version
   ```

2. **Foundry**
   ```bash
   forge --version
   anvil --version
   ```

3. **Python 3.8+** 和依赖
   ```bash
   python3 --version
   pip install web3 requests
   ```

### 一键验证

```bash
# 从项目根目录运行
python src/test/verify_invariants_runtime.py \
  --event extracted_contracts/2024-01/BarleyFinance_exp
```

## 📝 详细使用说明

### 方式1：端到端自动化验证（推荐）

完全自动化的验证流程：

```bash
python src/test/verify_invariants_runtime.py \
  --event extracted_contracts/2024-01/BarleyFinance_exp \
  --output my_verification_result.json \
  --verbose
```

**流程说明**：
1. ✅ 自动启动Anvil
2. ✅ 部署攻击状态
3. ✅ 编译Go Monitor
4. ✅ 执行攻击脚本
5. ✅ 分析交易trace
6. ✅ 评估不变量
7. ✅ 生成验证报告

**预期输出**：
```
════════════════════════════════════════════════════════════
🛡️  运行时不变量验证系统
════════════════════════════════════════════════════════════
事件: 2024-01/BarleyFinance_exp
输出: verification_runtime_result.json
════════════════════════════════════════════════════════════

🚀 [1/7] 启动 Anvil...
  ✓ Anvil 启动成功

📦 [2/7] 部署攻击状态...
  ✓ 状态部署成功

🔨 [3/7] 编译 Monitor...
  📥 下载Go依赖...
  🔧 编译 Monitor...
  ✓ Monitor 编译成功

💥 [4/7] 执行攻击脚本...
  ✓ 攻击执行完成
    交易hash: 0xabc123...

🔍 [5/7] 分析交易...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
交易分析结果
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
区块号: 2
Gas使用: 850234
状态: 1

📞 函数调用统计:
  0x3b30ba59: 20 次  (flash函数)

💰 余额变化:
  0x7b3a6ef...
    前: 1406062464485437940 wei
    后: 2500000000000000000 wei
    变化率: 77.81%

📈 关键指标:
  调用深度: 3
  重入深度: 2
  循环迭代: 20
  池子利用率: 98.5%

⚠️  [high] balance_change_rate 违规
   ID: inv_001
   消息: 攻击者地址余额在单笔交易中增长率不应超过500%
   详情:
     - threshold: 500
     - actual_rate: 777.81
     - address: 0x7b3a6eff1c9925e509c2b01a389238c1fcc462b6

[... 更多违规 ...]

✅ [6/7] 验证结果...
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  📊 验证结果
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  总违规数: 6
  违规不变量数: 6
    - Critical: 2
    - High: 3
    - Medium: 1

  🚨 攻击检测: 已检测到攻击！
  ✅ 检测准确率: 100.00%
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ [7/7] 验证成功！不变量正确识别了攻击。
```

### 方式2：手动步骤（调试模式）

适合调试和深入理解系统工作原理。

#### Step 1: 启动Anvil
```bash
# 终端1
anvil --block-base-fee-per-gas 0 --gas-price 0
```

#### Step 2: 部署状态
```bash
# 终端2
cd generated_deploy
python script/2024-01/deploy_BarleyFinance_exp.py
```

#### Step 3: 编译Monitor
```bash
cd autopath
go mod download
go build -o monitor ./cmd/monitor
```

#### Step 4: 执行攻击（获取交易hash）
```bash
forge test --match-path src/test/2024-01/BarleyFinance_exp.sol \
  --match-test testExploit \
  --rpc-url http://localhost:8545 \
  -vv
```

观察输出，获取交易hash（或从Anvil日志中查看）。

#### Step 5: 分析交易
```bash
cd autopath
./monitor \
  -rpc http://localhost:8545 \
  -event BarleyFinance_exp \
  -tx 0x<TRANSACTION_HASH> \
  -output ../verification_result.json \
  -v
```

#### Step 6: 查看结果
```bash
cat verification_result.json | jq
```

### 方式3：持续监控模式

实时监控Anvil链上的所有交易：

```bash
cd autopath
./monitor \
  -rpc http://localhost:8545 \
  -event BarleyFinance_exp \
  -monitor \
  -output ../monitoring_result.json \
  -v
```

在另一个终端执行交易，Monitor会实时分析并报告违规。

## 📊 输出格式

### verification_result.json

```json
{
  "event_name": "BarleyFinance_exp",
  "protocol": "BarleyFinance",
  "chain": "mainnet",
  "start_time": "2025-10-27T10:30:00Z",
  "end_time": "2025-10-27T10:30:15Z",
  "total_tx_monitored": 1,
  "violations": [
    {
      "invariant_id": "inv_001",
      "invariant_type": "balance_change_rate",
      "severity": "high",
      "message": "攻击者地址余额在单笔交易中增长率不应超过500%",
      "violated": true,
      "details": {
        "threshold": 500,
        "actual_rate": 777.81,
        "address": "0x7b3a6eff1c9925e509c2b01a389238c1fcc462b6"
      },
      "timestamp": "2025-10-27T10:30:10Z"
    },
    ...
  ],
  "summary": {
    "total_invariants": 6,
    "violated_invariants": 6,
    "total_violations": 6,
    "critical_violations": 2,
    "high_violations": 3,
    "medium_violations": 1,
    "violation_rate": 600.0,
    "attack_detected": true,
    "detection_accuracy": 100.0
  }
}
```

## 🔧 故障排除

### 问题1: "无法连接到RPC"
**解决**：确保Anvil正在运行
```bash
# 检查Anvil是否运行
curl -X POST http://localhost:8545 \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}'
```

### 问题2: "Monitor编译失败"
**解决**：检查Go版本和依赖
```bash
cd autopath
go version  # 应该 >= 1.21
go mod tidy
go build -o monitor ./cmd/monitor
```

### 问题3: "未检测到交易hash"
**解决**：手动从Anvil日志或`eth_getBlockByNumber`获取
```bash
cast block latest --rpc-url http://localhost:8545 -j | jq '.transactions[-1]'
```

### 问题4: "不变量未被违反"
**可能原因**：
1. 状态未正确部署
2. 攻击脚本执行失败
3. 不变量阈值设置过于宽松

**调试**：
```bash
# 验证部署状态
python src/test/verify_anvil_state.py \
  extracted_contracts/2024-01/BarleyFinance_exp/attack_state.json

# 使用-vvvv查看详细trace
forge test --match-path src/test/2024-01/BarleyFinance_exp.sol -vvvv
```

## 📁 项目结构

```
DeFiHackLabs/
├── autopath/                          # Go监控系统
│   ├── cmd/
│   │   └── monitor/
│   │       └── main.go               # Monitor主程序
│   ├── pkg/
│   │   ├── analyzer/
│   │   │   ├── trace_analyzer.go    # Trace分析器
│   │   │   └── data_extractor.go    # 数据提取器
│   │   ├── invariants/
│   │   │   ├── types.go             # 不变量接口
│   │   │   └── generated/
│   │   │       └── barleyfinance_invariants.go
│   │   ├── reporter/
│   │   │   └── reporter.go          # 报告生成器
│   │   └── types/
│   │       └── types.go             # 数据类型
│   ├── go.mod
│   └── monitor                       # 编译后的二进制
├── src/test/
│   ├── verify_invariants_runtime.py # 端到端验证脚本
│   ├── verify_invariants.py         # 元数据验证脚本
│   └── 2024-01/
│       └── BarleyFinance_exp.sol    # 攻击脚本
├── generated_invariants/
│   └── 2024-01/
│       └── BarleyFinance_exp/
│           └── invariants.json      # 不变量定义
└── extracted_contracts/
    └── 2024-01/
        └── BarleyFinance_exp/
            ├── attack_state.json    # 攻击状态
            └── addresses.json       # 地址列表
```

## 🎯 验证目标

系统验证以下内容：

1. ✅ **攻击检测**: 不变量能够检测到攻击交易
2. ✅ **准确率**: 所有6个不变量都应被违反
3. ✅ **实时性**: 能够在交易执行后立即分析
4. ✅ **完整性**: 捕获所有关键运行时数据（余额、调用、循环等）

## 🔍 高级用法

### 自定义不变量

修改 `autopath/pkg/invariants/generated/barleyfinance_invariants.go`：

```go
// 添加新的不变量规则
{
    ID:          "inv_007",
    Type:        "custom_check",
    Severity:    "high",
    Description: "自定义检查逻辑",
    Threshold:   100.0,
    Confidence:  0.9,
}
```

实现检查函数：

```go
func (inv *BarleyFinanceInvariants) checkCustom(rule *invariants.InvariantRule, txData *types.TransactionData) (bool, *types.ViolationDetail) {
    // 自定义检查逻辑
    return false, nil
}
```

### 添加新协议支持

1. 生成不变量JSON
2. 运行 `python src/test/integrate_invariants_to_monitor.py`
3. 重新编译Monitor

## 📚 参考资料

- **Trace Analyzer**: 使用 `debug_traceTransaction` 获取详细执行信息
- **Balance Changes**: 对比交易前后区块的余额
- **Loop Detection**: 通过JUMPI指令重复执行检测循环
- **Reentrancy**: 追踪调用栈中的地址重复

---

**生成时间**: 2025-10-27
**版本**: 1.0.0
**作者**: Claude Code
