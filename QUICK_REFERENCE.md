# 约束提取系统快速参考 (V3)

## 🚀 快速开始

### 单个协议提取
```bash
python3 DeFiHackLabs/extract_param_state_constraints.py \
  --protocol BarleyFinance_exp \
  --year-month 2024-01
```

### 批量提取
```bash
python3 DeFiHackLabs/extract_param_state_constraints.py \
  --batch \
  --filter 2024-01
```

### 自定义输出
```bash
python3 DeFiHackLabs/extract_param_state_constraints.py \
  --protocol MIMSpell2_exp \
  --year-month 2024-01 \
  --output /tmp/custom_output.json
```

## 📋 输出格式

### constraint_rules.json结构
```json
{
  "protocol": "协议名称",
  "year_month": "年月",
  "vulnerable_contract": {
    "address": "0x...",
    "name": "合约名"
  },
  "constraints": [
    {
      "function": "函数名",
      "signature": "函数签名",
      "attack_pattern": "攻击模式",
      "constraint": {
        "type": "inequality",
        "expression": "约束表达式",
        "semantics": "语义描述",
        "variables": {...},
        "danger_condition": "危险条件",
        "safe_condition": "安全条件"
      }
    }
  ],
  "storage_analysis": {...},
  "attack_metadata": {...}
}
```

## 🎯 支持的攻击模式

| 模式 | 关键词 | 状态 |
|------|--------|------|
| large_deposit | deposit, bond, stake, mint, supply | ✅ |
| drain_attack | withdraw, debond, unstake, redeem, burn | ✅ |
| borrow_attack | borrow | ✅ |
| repay_manipulation | repay, repayall, repayforall | ✅ |
| collateral_manipulation | addcollateral, removecollateral, liquidate | ✅ |
| flashloan_attack | flashloan, flash | ⏳ |
| swap_manipulation | swap, swapmanual, swapexact | ⏳ |
| price_oracle_attack | trade, exchange, buy, sell | ⏳ |
| reentrancy_attack | callback, onflashloan, receive, fallback | ⏳ |
| governance_attack | vote, propose, execute, delegate | ⏳ |
| bridge_attack | bridge, relay, lock, unlock | ⏳ |
| nft_manipulation | claim, harvest, compound | ⏳ |

## 📊 V3性能指标

| 指标 | 数值 |
|------|------|
| 合约地址识别率 | **100%** (19/19) |
| 合约名称识别率 | 89.5% (17/19) |
| 函数调用识别率 | 63.2% (12/19) |
| 约束生成成功率 | 36.8% (7/19) |
| 总约束规则数 | 27个 |
| 平均每协议约束数 | 3.9个 |

## ✅ 成功案例

### BarleyFinance_exp
- 合约: wBARL (0x04c80bb...)
- 函数调用: 3个 (flash, bond, debond)
- 约束: 3个 (large_deposit)
- 攻击循环: 20次

### MIMSpell2_exp
- 合约: CauldronV4 (0x7259e15...)
- 函数调用: 15个
- 约束: 8个 (borrow x3, repay x3, collateral x2)
- 攻击循环: 90次
- **亮点**: 复杂借贷攻击链成功识别

### RadiantCapital_exp
- 合约: RadiantLendingPool (0xf4b1486...)
- 函数调用: 7个
- 约束: 6个 (deposit x3, withdraw x2)
- 攻击循环: 151次

## 🔧 常见问题

### Q: 为什么某些协议没有生成约束?

**A**: 可能的原因:
1. 合约名称未识别 (检查注释格式)
2. 函数调用未匹配到攻击模式关键词
3. 参数未被识别为dynamic
4. Storage变化为空

### Q: 如何添加新的攻击模式?

**A**: 在`ATTACK_PATTERNS`字典中添加:
```python
'new_attack': {
    'keywords': ['keyword1', 'keyword2'],
    'description': '攻击描述',
    'constraint_template': 'param > state * threshold'
}
```
然后在`_generate_constraint_from_pattern()`中实现约束生成逻辑。

### Q: 如何查看详细的调试信息?

**A**: 查看日志输出中的:
- `被攻击合约`: 合约识别结果
- `识别到 X 个函数调用`: 函数调用识别结果
- `生成约束: X 个`: 约束生成结果

## 📁 文件位置

### 输入文件
- 攻击脚本: `DeFiHackLabs/src/test/{year-month}/{Protocol}_exp.sol`
- 状态数据: `DeFiHackLabs/extracted_contracts/{year-month}/{Protocol}_exp/attack_state.json`
- 状态数据(后): `DeFiHackLabs/extracted_contracts/{year-month}/{Protocol}_exp/attack_state_after.json`

### 输出文件
- 约束规则: `DeFiHackLabs/extracted_contracts/{year-month}/{Protocol}_exp/constraint_rules.json`

### 工具脚本
- 主脚本: `DeFiHackLabs/extract_param_state_constraints.py`

### 文档
- 测试报告: `DeFiHackLabs/CONSTRAINT_EXTRACTION_V2_TEST_REPORT.md`
- V2总结: `DeFiHackLabs/CONSTRAINT_EXTRACTION_V2_SUMMARY.md`
- V3报告: `DeFiHackLabs/CONTRACT_RECOGNITION_ENHANCEMENT_REPORT.md`
- 演进总结: `DeFiHackLabs/CONSTRAINT_EXTRACTION_EVOLUTION_SUMMARY.md`
- 模式参考: `DeFiHackLabs/ATTACK_PATTERNS_REFERENCE.md`

## 🛠️ 代码结构

```
extract_param_state_constraints.py
├── AttackScriptParser
│   ├── _extract_vulnerable_contract()  # V3增强: 5种模式
│   ├── _infer_contract_name()         # V3新增: 4种策略
│   ├── _extract_attack_calls()
│   ├── _extract_balanced_parens()
│   ├── _parse_parameters()
│   └── _extract_loop_info()
├── StorageAnalyzer
│   ├── get_contract_storage()
│   └── identify_changed_slots()
├── ConstraintGenerator
│   ├── ATTACK_PATTERNS                 # V2扩展: 11种模式
│   ├── generate()
│   └── _generate_constraint_from_pattern()  # V2实现11种
└── ConstraintExtractor
    ├── extract_single()
    ├── save_result()
    └── batch_extract()
```

## 📈 版本历史

| 版本 | 日期 | 关键改进 | 约束生成率 |
|------|------|---------|-----------|
| V1 | 2025-01-21 | 基础框架,4种模式 | 21.1% |
| V2 | 2025-01-21 | 扩展到11种模式 | 31.6% |
| V3 | 2025-01-21 | 增强合约识别 | **36.8%** |

## 🎯 下一步路线图

### Phase 1: 参数识别优化 (高优先级)
- 改进is_dynamic判断逻辑
- 支持更多参数表达式
- 预期: +5%约束生成率

### Phase 2: 变量名容错 (中优先级)
- 支持变量名变体匹配
- 预期: +3个协议识别到函数调用

### Phase 3: 关键词扩展 (中优先级)
- 分析失败协议的函数名
- 补充攻击模式关键词
- 预期: +2-3个约束

### Phase 4: Stage 2集成 (低优先级)
- 集成Z3约束求解器
- 生成fuzzing种子
- 功能性里程碑

## 📞 获取帮助

```bash
# 查看帮助信息
python3 DeFiHackLabs/extract_param_state_constraints.py --help
```

**输出**:
```
usage: extract_param_state_constraints.py [-h] [--protocol PROTOCOL]
                                          [--year-month YEAR_MONTH]
                                          [--batch] [--filter FILTER]
                                          [--output OUTPUT]

从攻击PoC中提取参数-状态约束关系

optional arguments:
  --protocol PROTOCOL     协议名称（如 BarleyFinance_exp）
  --year-month YEAR_MONTH 年月（如 2024-01）
  --batch                 批量处理模式
  --filter FILTER         批量模式下的年月过滤器（如 2024-01）
  --output OUTPUT         自定义输出路径
```

---

**最后更新**: 2025-01-21  
**当前版本**: V3  
**维护者**: FirewallOnchain Team
