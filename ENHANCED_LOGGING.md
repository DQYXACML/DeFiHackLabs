# 增强的日志和耗时统计功能

## 概述

`extract_param_state_constraints_v2_5.py` 脚本已增强，支持详细的耗时日志和文件输出功能。

## 新增功能

### 1. 自动日志文件输出

所有日志信息会自动保存到文件中，同时继续在控制台显示。

**默认日志路径**: `logs/extract_constraints_YYYYMMDD_HHMMSS.log`

例如: `logs/extract_constraints_20250122_143025.log`

### 2. 自定义日志文件路径

可以通过 `--log-file` 参数指定自定义日志文件路径:

```bash
python3 extract_param_state_constraints_v2_5.py \
    --batch --filter 2024-01 \
    --use-firewall-config --use-slither \
    --log-file my_custom_logs/batch_analysis.log
```

### 3. 详细的耗时统计

脚本会自动记录每个关键步骤的耗时:

- **总体耗时**: 整个批量提取过程的总时间
- **单协议耗时**: 每个协议的提取时间
- **子任务耗时**:
  - 加载防火墙配置
  - 解析攻击脚本
  - 状态差异分析
  - 获取分析目标
  - 分析状态变化
  - 生成约束

### 4. 进度显示

批量模式下会显示实时进度:

```
进度: 15/50 - BarleyFinance_exp
```

## 使用示例

### 示例 1: 批量处理并保存日志

```bash
python3 extract_param_state_constraints_v2_5.py \
    --batch --filter 2024-01 \
    --use-firewall-config --use-slither
```

输出:
- 控制台: 彩色实时日志
- 文件: `logs/extract_constraints_20250122_143025.log`

### 示例 2: 单个协议分析

```bash
python3 extract_param_state_constraints_v2_5.py \
    --protocol BarleyFinance_exp \
    --year-month 2024-01 \
    --use-firewall-config
```

### 示例 3: 自定义日志路径

```bash
python3 extract_param_state_constraints_v2_5.py \
    --batch --filter 2024-01 \
    --log-file results/analysis_$(date +%Y%m%d).log
```

## 日志格式

### 控制台输出 (带颜色)

```
[⏱] 开始: 提取协议: BarleyFinance_exp
[INFO] 开始提取约束 (V2): BarleyFinance_exp
[⏱] 完成: 提取协议: BarleyFinance_exp - 耗时: 3.42s
```

### 日志文件格式

```
2025-01-22 14:30:25,123 [INFO] 日志文件: logs/extract_constraints_20250122_143025.log
2025-01-22 14:30:25,124 [INFO] 开始时间: 2025-01-22 14:30:25
2025-01-22 14:30:25,125 [INFO] ⏱ 开始: 批量提取
2025-01-22 14:30:25,130 [INFO] 准备处理 50 个协议...
2025-01-22 14:30:25,135 [INFO] 进度: 1/50 - BarleyFinance_exp
2025-01-22 14:30:28,567 [INFO] ✓ 生成约束: 3 个
2025-01-22 14:45:12,890 [INFO] ⏱ 完成: 批量提取 - 耗时: 14m 47.8s
2025-01-22 14:45:12,891 [INFO] ✓ 总耗时: 14m 47.8s
```

## 耗时格式化

系统会自动将耗时格式化为易读的形式:

- `< 1秒`: `250ms`
- `< 1分钟`: `3.42s`
- `< 1小时`: `2m 15.3s`
- `≥ 1小时`: `1h 23m 45s`

## 日志级别

系统支持以下日志级别:

- `[INFO]` (蓝色): 一般信息
- `[SUCCESS]` (绿色): 成功消息
- `[WARNING]` (黄色): 警告信息
- `[ERROR]` (红色): 错误信息
- `[DEBUG]` (青色): 调试信息
- `[⏱]` (紫色): 耗时统计

## 批量处理统计

批量处理完成后会显示汇总信息:

```
============================================================
[SUCCESS] 批量提取完成!
[SUCCESS] 总计: 50 个协议
[SUCCESS] 成功: 48 个
[ERROR] 失败: 2 个
============================================================
[SUCCESS] 总耗时: 14m 47.8s
[INFO] 结束时间: 2025-01-22 14:45:12
============================================================
[SUCCESS] 日志已保存到: logs/extract_constraints_20250122_143025.log
```

## 注意事项

1. **日志目录**: `logs/` 目录会自动创建（如果不存在）
2. **文件编码**: 日志文件使用 UTF-8 编码
3. **时间戳**: 使用本地时区时间
4. **并发安全**: 日志系统是线程安全的

## 查看历史日志

所有历史日志都保存在 `logs/` 目录中，可以随时查看:

```bash
# 查看最新日志
tail -f logs/extract_constraints_*.log

# 搜索特定协议的日志
grep "BarleyFinance_exp" logs/extract_constraints_20250122_143025.log

# 查看所有耗时统计
grep "⏱" logs/extract_constraints_20250122_143025.log

# 查看错误信息
grep "ERROR" logs/extract_constraints_20250122_143025.log
```

## 性能分析

通过耗时日志可以识别性能瓶颈:

```bash
# 提取所有耗时信息并排序
grep "完成:" logs/extract_constraints_20250122_143025.log | \
    sort -t':' -k3 -rn | \
    head -10
```

这将显示耗时最长的前10个任务。
