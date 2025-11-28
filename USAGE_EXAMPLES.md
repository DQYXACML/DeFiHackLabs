# extract_param_state_constraints_v2_5.py 使用示例

## 快速开始

### 示例 1: 批量处理（推荐）

```bash
python3 extract_param_state_constraints_v2_5.py \
    --batch \
    --filter 2024-01 \
    --use-firewall-config \
    --use-slither
```

**输出**:
- 控制台: 彩色实时日志 + 进度显示
- 文件: `logs/extract_constraints_YYYYMMDD_HHMMSS.log`

**预期结果**:
```
[⏱] 开始: 批量提取
[INFO] 准备处理 50 个协议...
============================================================
[INFO] 进度: 1/50 - BarleyFinance_exp
============================================================
[⏱] 开始: 提取协议: BarleyFinance_exp
[⏱] 开始: BarleyFinance_exp - 解析攻击脚本
[⏱] 完成: BarleyFinance_exp - 解析攻击脚本 - 耗时: 2.35s
[⏱] 开始: BarleyFinance_exp - 状态差异分析
[⏱] 完成: BarleyFinance_exp - 状态差异分析初始化 - 耗时: 150ms
...
[SUCCESS] 生成约束: 3 个
[⏱] 完成: 提取协议: BarleyFinance_exp - 耗时: 3.42s
...
[⏱] 完成: 批量提取 - 耗时: 14m 47.8s
============================================================
[SUCCESS] 批量提取完成!
[SUCCESS] 总计: 50 个协议
[SUCCESS] 成功: 48 个
[ERROR] 失败: 2 个
============================================================
[SUCCESS] 总耗时: 14m 47.8s
[SUCCESS] 日志已保存到: logs/extract_constraints_20250122_143025.log
```

### 示例 2: 单个协议分析

```bash
python3 extract_param_state_constraints_v2_5.py \
    --protocol BarleyFinance_exp \
    --year-month 2024-01 \
    --use-firewall-config
```

**耗时信息**:
```
[⏱] 开始: 提取协议: BarleyFinance_exp
[⏱] 开始: BarleyFinance_exp - 加载防火墙配置
[⏱] 完成: BarleyFinance_exp - 加载防火墙配置 - 耗时: 10ms
[⏱] 开始: BarleyFinance_exp - 解析攻击脚本
[⏱] 完成: BarleyFinance_exp - 解析攻击脚本 - 耗时: 2.35s
[⏱] 开始: BarleyFinance_exp - 获取分析目标
[⏱] 完成: BarleyFinance_exp - 获取分析目标 - 耗时: 50ms
[⏱] 开始: BarleyFinance_exp - 分析状态变化
[⏱] 完成: BarleyFinance_exp - 分析状态变化 - 耗时: 120ms
[⏱] 开始: BarleyFinance_exp - 生成约束
[⏱] 完成: BarleyFinance_exp - 生成约束 - 耗时: 850ms
[⏱] 完成: 提取协议: BarleyFinance_exp - 耗时: 3.42s
```

### 示例 3: 自定义日志路径

```bash
# 使用日期作为日志文件名
python3 extract_param_state_constraints_v2_5.py \
    --batch --filter 2024-01 \
    --log-file "results/analysis_$(date +%Y%m%d).log"
```

### 示例 4: 查看历史日志

```bash
# 查看最新日志
tail -f logs/extract_constraints_*.log

# 搜索特定协议
grep "BarleyFinance_exp" logs/extract_constraints_20250122_143025.log

# 查看所有耗时统计
grep "⏱.*完成:" logs/extract_constraints_20250122_143025.log

# 查看错误信息
grep "ERROR" logs/extract_constraints_20250122_143025.log

# 统计总耗时
grep "总耗时:" logs/extract_constraints_20250122_143025.log
```

### 示例 5: 性能分析

```bash
# 找出耗时最长的任务
grep "完成:" logs/extract_constraints_20250122_143025.log | \
    awk -F'耗时: ' '{print $2, $0}' | \
    sort -rn | \
    head -10

# 统计各个阶段的平均耗时
grep "解析攻击脚本.*完成:" logs/extract_constraints_20250122_143025.log | \
    wc -l
```

## 日志文件格式

### 控制台输出（带颜色）

- `[INFO]` - 蓝色: 一般信息
- `[SUCCESS]` - 绿色: 成功消息
- `[WARNING]` - 黄色: 警告信息
- `[ERROR]` - 红色: 错误信息
- `[⏱]` - 紫色: 耗时统计

### 日志文件格式（纯文本）

```
2025-01-22 14:30:25,123 [INFO] 日志文件: logs/extract_constraints_20250122_143025.log
2025-01-22 14:30:25,124 [INFO] 开始时间: 2025-01-22 14:30:25
2025-01-22 14:30:25,125 [INFO] ⏱ 开始: 批量提取
2025-01-22 14:30:28,567 [INFO] ✓ 生成约束: 3 个
2025-01-22 14:45:12,890 [INFO] ⏱ 完成: 批量提取 - 耗时: 14m 47.8s
```

## 关键耗时指标

| 任务阶段 | 典型耗时 | 说明 |
|---------|---------|------|
| 加载防火墙配置 | < 50ms | 读取JSON配置文件 |
| 解析攻击脚本 | 1-3s | Slither AST解析（如启用） |
| 状态差异分析 | 100-500ms | 分析attack_state.json |
| 获取分析目标 | 50-200ms | 确定被保护合约 |
| 分析状态变化 | 100-300ms | 计算slot变化 |
| 生成约束 | 500ms-2s | 关联参数与状态变化 |
| **单协议总耗时** | **2-5s** | 完整分析一个协议 |
| **批量50个协议** | **10-20m** | 取决于协议复杂度 |

## 常见问题

### Q: 日志文件过大怎么办？

使用日志轮转或定期清理:

```bash
# 只保留最近7天的日志
find logs/ -name "extract_constraints_*.log" -mtime +7 -delete

# 压缩旧日志
find logs/ -name "*.log" -mtime +1 -exec gzip {} \;
```

### Q: 如何只看错误日志？

```bash
grep -E "\[ERROR\]|\[WARNING\]" logs/extract_constraints_20250122_143025.log
```

### Q: 如何监控实时进度？

```bash
# 在另一个终端中监控
tail -f logs/extract_constraints_*.log | grep -E "进度:|完成:"
```

### Q: 如何生成性能报告？

```bash
# 提取所有耗时并生成统计
grep "完成:.*耗时:" logs/extract_constraints_20250122_143025.log | \
    awk -F'耗时: ' '{print $1, $2}' > performance_report.txt
```

## 高级用法

### 并行批量处理

如果需要更快的处理速度，可以手动拆分年月并并行运行:

```bash
# 终端1
python3 extract_param_state_constraints_v2_5.py \
    --batch --filter 2024-01 \
    --log-file logs/batch_2024_01.log &

# 终端2
python3 extract_param_state_constraints_v2_5.py \
    --batch --filter 2024-02 \
    --log-file logs/batch_2024_02.log &

# 等待所有任务完成
wait
```

### 条件处理

只处理有状态变化的协议:

```bash
# 先运行一次收集统计
python3 extract_param_state_constraints_v2_5.py --batch --filter 2024-01

# 从日志中提取有状态变化的协议
grep "个slot变化" logs/extract_constraints_*.log | \
    awk -F': ' '{print $2}' | \
    awk '{print $1}' > protocols_with_changes.txt

# 针对性重新处理
while read protocol; do
    python3 extract_param_state_constraints_v2_5.py \
        --protocol "$protocol" --year-month 2024-01 \
        --use-firewall-config
done < protocols_with_changes.txt
```
