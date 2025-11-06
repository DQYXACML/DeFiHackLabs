# 动态不变量检测系统 - 使用说明

本系统实现了**方案二：动态执行检测**，通过在Anvil上实际重放攻击来验证不变量违规情况。

## 📋 系统概述

### 核心功能
- ✅ 在Anvil上重放攻击交易
- ✅ 捕获攻击前后的存储状态
- ✅ 评估存储级和运行时不变量
- ✅ 生成详细的Markdown和JSON报告
- ✅ 支持批量并行处理

### 检测流程
```
1. 启动Anvil → 2. 部署状态 → 3. 拍摄前快照 → 4. 执行攻击 →
5. 拍摄后快照 → 6. Monitor分析 → 7. 评估不变量 → 8. 生成报告
```

## 🛠️ 系统架构

### 核心组件

#### 1. `invariant_evaluator.py` - 不变量评估引擎
**支持的不变量类型**:
- `share_price_stability`: 份额价格稳定性（Vault攻击）
- `supply_backing_consistency`: 供应支撑一致性
- `bounded_change_rate`: 变化率限制
- `balance_change_rate`: 余额变化率
- `loop_iterations`: 循环迭代次数
- `flash_loan_depth`: 闪电贷深度
- `call_sequence_pattern`: 调用序列模式

#### 2. `storage_comparator.py` - 存储对比工具
- 批量查询存储槽（支持RPC批量请求）
- Before/After状态对比
- 变化率计算

#### 3. `runtime_metrics_extractor.py` - 运行时指标提取器
- 集成Go Monitor分析
- 回退到cast trace分析
- 提取gas、调用深度、重入深度、循环次数等指标

#### 4. `dynamic_invariant_checker.py` - 核心动态检测器
- 完整的端到端检测流程
- Anvil生命周期管理
- 自动提取攻击交易hash

#### 5. `batch_dynamic_checker.py` - 批量处理协调器
- 多进程并行处理
- 独立端口分配（避免冲突）
- 进度跟踪和失败容错

#### 6. `report_builder.py` - 报告生成器
- Markdown人类可读报告
- JSON机器可读报告
- CSV批量汇总

## 🚀 快速开始

### 前置条件

1. **已安装工具**:
   ```bash
   # Foundry (forge, cast, anvil)
   forge --version
   cast --version
   anvil --version

   # Python 3.8+
   python --version

   # Go (用于Monitor，可选)
   go version
   ```

2. **必需文件**:
   - `extracted_contracts/{year-month}/{event_name}/attack_state.json`
   - `extracted_contracts/{year-month}/{event_name}/invariants.json`
   - `src/test/{year-month}/{event_name}.sol`

### 测试系统组件

```bash
# 运行组件测试（验证系统是否正常工作）
python src/test/test_dynamic_system.py
```

预期输出:
```
🧪 动态检测系统组件测试

======================================================================
测试汇总
======================================================================
  扫描功能: ✅ 通过
  不变量评估器: ✅ 通过
  存储对比器: ✅ 通过
  报告生成器: ✅ 通过

总计: 4/4 通过
```

## 📖 使用方法

### 方法1: 单个攻击检测

```bash
# 基本用法
python src/test/dynamic_invariant_checker.py \
  --event-name Gamma_exp \
  --year-month 2024-01

# 使用自定义端口
python src/test/dynamic_invariant_checker.py \
  --event-name Gamma_exp \
  --year-month 2024-01 \
  --anvil-port 8546

# 跳过Monitor分析（仅检测存储级不变量）
python src/test/dynamic_invariant_checker.py \
  --event-name CitadelFinance_exp \
  --year-month 2024-01 \
  --skip-monitor

# 指定输出目录
python src/test/dynamic_invariant_checker.py \
  --event-name Gamma_exp \
  --year-month 2024-01 \
  --output-dir my_reports/
```

### 方法2: 批量检测

```bash
# 检测2024-01目录下的所有攻击（4个并发worker）
python src/test/batch_dynamic_checker.py \
  --filter 2024-01 \
  --workers 4

# 检测特定攻击列表
python src/test/batch_dynamic_checker.py \
  --events Gamma_exp,CitadelFinance_exp,Bmizapper_exp \
  --workers 3

# 使用更多worker加速（最多10个，受端口限制）
python src/test/batch_dynamic_checker.py \
  --filter 2024-01 \
  --workers 8 \
  --base-port 8545

# 跳过Monitor分析（更快，但无运行时指标）
python src/test/batch_dynamic_checker.py \
  --filter 2024-01 \
  --skip-monitor \
  --workers 6
```

## 📊 输出报告

### 单个攻击报告

#### Markdown报告
路径: `reports/dynamic_checks/{event_name}_dynamic_report.md`

示例:
```markdown
# 动态不变量检测报告 - Gamma_exp

## 📋 基本信息
- **攻击名称**: Gamma_exp
- **年月**: 2024-01
- **攻击交易**: `0x123...`

## 📊 执行摘要
- **总不变量数**: 5
- **违规数量**: 3 ❌
- **通过数量**: 2 ✅
- **违规率**: 60.0%

## ❌ 违规详情

### 1. [SINV_001] share_price_stability
**严重程度**: `CRITICAL`
**描述**: Vault share price must not change more than 5% per transaction
**阈值**: `5%`
**实际值**: `87.3%` 🚨
**影响**: Allows attacker to mint underpriced shares

**证据**:
```json
{
  "totalSupply_before": 1000000,
  "totalSupply_after": 1500000,
  "reserves_before": 5000000,
  "reserves_after": 3000000,
  "share_price_change_pct": "87.3%"
}
```
```

#### JSON报告
路径: `reports/dynamic_checks/{event_name}_dynamic_report.json`

```json
{
  "report_metadata": {
    "event_name": "Gamma_exp",
    "year_month": "2024-01",
    "generated_at": "2025-11-04T18:30:00",
    "detection_method": "dynamic_execution"
  },
  "summary": {
    "total_invariants": 5,
    "violations_detected": 3,
    "passed": 2,
    "violation_rate": 0.6
  },
  "violation_results": [...]
}
```

### 批量检测报告

#### CSV汇总
路径: `reports/batch_dynamic/batch_summary.csv`

```csv
攻击名称,年月,总不变量数,违规数量,通过数量,违规率(%),状态,检测时间
Gamma_exp,2024-01,5,3,2,60.0,Success,2025-11-04 18:30:00
CitadelFinance_exp,2024-01,4,2,2,50.0,Success,2025-11-04 18:35:00
...
```

#### Markdown汇总
路径: `reports/batch_dynamic/batch_summary.md`

## 🔍 2024-01目录检测结果

运行组件测试后，系统扫描到**13个可检测的攻击**:

```
✓ MIMSpell2_exp
✓ SocketGateway_exp
✓ WiseLending03_exp
✓ OrbitChain_exp
✓ Bmizapper_exp
✓ CitadelFinance_exp
✓ RadiantCapital_exp
✓ WiseLending02_exp
✓ Gamma_exp
✓ LQDX_alert_exp
✓ NBLGAME_exp
✓ XSIJ_exp
✓ DAO_SoulMate_exp
```

这些攻击都具备完整的：
- ✅ `attack_state.json` （攻击状态）
- ✅ `invariants.json` （不变量规则）
- ✅ 攻击脚本 `.sol` 文件

## ⚙️ 高级配置

### 端口管理

批量检测时，每个worker使用独立端口：
- Worker 0: 8545
- Worker 1: 8546
- Worker 2: 8547
- ...

如果8545端口被占用，可以使用 `--base-port` 指定起始端口：
```bash
python src/test/batch_dynamic_checker.py \
  --filter 2024-01 \
  --base-port 9000 \
  --workers 4
# 将使用端口 9000, 9001, 9002, 9003
```

### Monitor集成

默认情况下，系统会尝试调用Go Monitor分析交易trace。如果Monitor不可用或编译失败，系统会自动回退到`cast`命令提取基本指标。

**跳过Monitor**（更快，但缺少部分运行时指标）:
```bash
python src/test/dynamic_invariant_checker.py \
  --event-name Gamma_exp \
  --year-month 2024-01 \
  --skip-monitor
```

### 性能优化

**批量检测优化**:
```bash
# 1. 使用更多worker（推荐CPU核心数）
python src/test/batch_dynamic_checker.py \
  --filter 2024-01 \
  --workers 8 \
  --skip-monitor  # 跳过Monitor加速

# 2. 处理子集进行快速验证
python src/test/batch_dynamic_checker.py \
  --events Gamma_exp,CitadelFinance_exp \
  --workers 2
```

## 🐛 故障排查

### 常见问题

#### 1. Anvil启动失败
```
错误: Anvil启动失败
```

**解决方案**:
- 检查端口是否被占用: `lsof -i :8545`
- 使用不同端口: `--anvil-port 8546`
- 确保anvil已安装: `anvil --version`

#### 2. forge test执行失败
```
错误: forge test执行失败
```

**解决方案**:
- 手动测试攻击脚本是否能编译: `forge test --match-path src/test/2024-01/Gamma_exp.sol`
- 检查依赖: `forge install`
- 查看详细错误: 添加 `-vvv` 参数

**注意**: 系统已自动配置跳过以下有问题的文件:
- `src/test/2024-11/proxy_b7e1_exp.sol`
- `src/test/2025-05/Corkprotocol_exp.sol`

#### 3. 未找到交易hash
```
警告: 未能提取交易hash
```

**解决方案**:
- 这通常不影响存储级不变量检测
- 仅影响运行时指标提取
- 可以使用 `--skip-monitor` 跳过

#### 4. Monitor编译失败
```
错误: Monitor可执行文件不存在
```

**解决方案**:
- 系统会自动尝试编译Monitor
- 如果失败，会回退到cast分析
- 或手动编译: `cd autopath && go build -o monitor ./cmd/monitor`

## 📚 扩展开发

### 添加新的不变量类型

编辑 `invariant_evaluator.py`:

```python
def _eval_my_custom_invariant(
    self,
    invariant: Dict,
    storage_changes: Dict,
    runtime_metrics: Dict
) -> ViolationResult:
    """评估自定义不变量"""

    # 提取数据
    actual_value = ...
    threshold = invariant.get('threshold')

    # 检测逻辑
    is_violated = actual_value > threshold

    return ViolationResult(
        invariant_id=invariant.get('id'),
        invariant_type='my_custom_invariant',
        severity=ViolationSeverity(invariant.get('severity', 'medium')),
        violated=is_violated,
        threshold=threshold,
        actual_value=actual_value,
        description=invariant.get('description', ''),
        impact=invariant.get('violation_impact', ''),
        evidence={...}
    )
```

然后在 `__init__` 中注册：
```python
self.evaluators = {
    ...
    'my_custom_invariant': self._eval_my_custom_invariant,
}
```

## 📝 下一步

1. **运行批量检测**: 对2024-01目录的13个攻击进行完整检测
   ```bash
   python src/test/batch_dynamic_checker.py --filter 2024-01 --workers 4
   ```

2. **分析报告**: 查看生成的报告，了解哪些不变量被违规

3. **优化不变量**: 根据检测结果调整不变量阈值或添加新规则

4. **扩展到其他目录**: 对其他年月的攻击进行检测

## ⚡ 性能数据

基于测试环境的预估：
- **单个攻击检测**: 30-120秒（取决于攻击复杂度）
- **批量检测（13个攻击，4 workers）**: ~8-15分钟
- **批量检测（13个攻击，8 workers）**: ~5-10分钟

## 📞 支持

如有问题或需要改进，请查看：
- 测试脚本: `src/test/test_dynamic_system.py`
- 组件测试输出
- 生成的报告文件

---

**系统状态**: ✅ 所有组件测试通过，可以投入使用！
