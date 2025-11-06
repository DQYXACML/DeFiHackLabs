package reporter

import (
	"autopath/pkg/types"
	"encoding/json"
	"fmt"
	"os"
	"time"

	"github.com/fatih/color"
)

// Reporter 报告生成器
type Reporter struct {
	report        *types.VerificationReport
	violations    []types.ViolationDetail
	startTime     time.Time
	txCount       int
	verbose       bool
}

// NewReporter 创建报告生成器
func NewReporter(eventName, protocol, chain string, verbose bool) *Reporter {
	return &Reporter{
		report: &types.VerificationReport{
			EventName:  eventName,
			Protocol:   protocol,
			Chain:      chain,
			StartTime:  time.Now(),
			Violations: []types.ViolationDetail{},
		},
		violations: []types.ViolationDetail{},
		startTime:  time.Now(),
		verbose:    verbose,
	}
}

// RecordTransaction 记录交易监控
func (r *Reporter) RecordTransaction() {
	r.txCount++
	r.report.TotalTxMonitored = r.txCount
}

// RecordViolation 记录不变量违规
func (r *Reporter) RecordViolation(violation types.ViolationDetail) {
	violation.Timestamp = time.Now()
	r.violations = append(r.violations, violation)
	r.report.Violations = append(r.report.Violations, violation)

	// 实时打印违规（如果verbose模式）
	if r.verbose {
		r.printViolation(&violation)
	}
}

// RecordTransactionData 记录交易运行时数据
func (r *Reporter) RecordTransactionData(txData *types.TransactionData) {
	r.report.TransactionData = txData
}

// printViolation 打印单个违规
func (r *Reporter) printViolation(v *types.ViolationDetail) {
	severityColor := color.New(color.FgYellow)
	switch v.Severity {
	case "critical":
		severityColor = color.New(color.FgRed, color.Bold)
	case "high":
		severityColor = color.New(color.FgRed)
	case "medium":
		severityColor = color.New(color.FgYellow)
	}

	fmt.Printf("\n")
	severityColor.Printf("⚠️  [%s] %s 违规\n", v.Severity, v.InvariantType)
	fmt.Printf("   ID: %s\n", v.InvariantID)
	fmt.Printf("   消息: %s\n", v.Message)
	if len(v.Details) > 0 {
		fmt.Printf("   详情:\n")
		for k, val := range v.Details {
			fmt.Printf("     - %s: %v\n", k, val)
		}
	}
}

// Finalize 完成报告
func (r *Reporter) Finalize() {
	r.report.EndTime = time.Now()
	r.calculateSummary()
}

// calculateSummary 计算摘要
func (r *Reporter) calculateSummary() {
	summary := &r.report.Summary

	// 统计不同严重级别的违规
	violatedInvariants := make(map[string]bool)
	for _, v := range r.violations {
		violatedInvariants[v.InvariantID] = true

		switch v.Severity {
		case "critical":
			summary.CriticalViolations++
		case "high":
			summary.HighViolations++
		case "medium":
			summary.MediumViolations++
		}
	}

	summary.ViolatedInvariants = len(violatedInvariants)
	summary.TotalViolations = len(r.violations)

	// 判断是否检测到攻击
	if summary.CriticalViolations > 0 || summary.HighViolations > 0 {
		summary.AttackDetected = true
	}

	// 计算违规率
	if r.txCount > 0 {
		summary.ViolationRate = float64(summary.TotalViolations) / float64(r.txCount) * 100
	}

	// 计算检测准确率（如果检测到攻击且有critical/high违规，则认为准确）
	if summary.AttackDetected && (summary.CriticalViolations > 0 || summary.HighViolations > 0) {
		summary.DetectionAccuracy = 100.0
	}
}

// PrintSummary 打印摘要到终端
func (r *Reporter) PrintSummary() {
	summary := r.report.Summary

	fmt.Printf("\n")
	fmt.Println("════════════════════════════════════════════════════════════")
	color.New(color.FgCyan, color.Bold).Println("验证总结")
	fmt.Println("════════════════════════════════════════════════════════════")

	fmt.Printf("协议: %s\n", r.report.Protocol)
	fmt.Printf("事件: %s\n", r.report.EventName)
	fmt.Printf("监控时间: %s - %s (耗时: %.2fs)\n",
		r.report.StartTime.Format("15:04:05"),
		r.report.EndTime.Format("15:04:05"),
		r.report.EndTime.Sub(r.report.StartTime).Seconds(),
	)
	fmt.Printf("监控交易数: %d\n", r.report.TotalTxMonitored)
	fmt.Println("────────────────────────────────────────────────────────────")

	// 违规统计
	fmt.Printf("总违规数: %d\n", summary.TotalViolations)
	fmt.Printf("违规不变量数: %d\n", summary.ViolatedInvariants)

	if summary.CriticalViolations > 0 {
		color.New(color.FgRed, color.Bold).Printf("  - Critical: %d\n", summary.CriticalViolations)
	}
	if summary.HighViolations > 0 {
		color.New(color.FgRed).Printf("  - High: %d\n", summary.HighViolations)
	}
	if summary.MediumViolations > 0 {
		color.New(color.FgYellow).Printf("  - Medium: %d\n", summary.MediumViolations)
	}

	fmt.Printf("违规率: %.2f%%\n", summary.ViolationRate)
	fmt.Println("────────────────────────────────────────────────────────────")

	// 攻击检测结果
	if summary.AttackDetected {
		color.New(color.FgRed, color.Bold).Printf("🚨 攻击检测: 已检测到攻击！\n")
		color.New(color.FgGreen, color.Bold).Printf("✅ 检测准确率: %.2f%%\n", summary.DetectionAccuracy)
	} else {
		color.New(color.FgGreen).Printf("✓ 未检测到攻击\n")
	}

	fmt.Println("════════════════════════════════════════════════════════════")
}

// SaveToFile 保存报告到文件
func (r *Reporter) SaveToFile(filename string) error {
	// 确保报告已完成
	if r.report.EndTime.IsZero() {
		r.Finalize()
	}

	// 序列化为JSON
	data, err := json.MarshalIndent(r.report, "", "  ")
	if err != nil {
		return fmt.Errorf("序列化报告失败: %w", err)
	}

	// 写入文件
	if err := os.WriteFile(filename, data, 0644); err != nil {
		return fmt.Errorf("写入文件失败: %w", err)
	}

	color.New(color.FgGreen).Printf("✓ 报告已保存到: %s\n", filename)
	return nil
}

// GetReport 获取报告
func (r *Reporter) GetReport() *types.VerificationReport {
	return r.report
}

// GetViolationCount 获取违规数量
func (r *Reporter) GetViolationCount() int {
	return len(r.violations)
}

// HasCriticalViolations 是否有critical违规
func (r *Reporter) HasCriticalViolations() bool {
	for _, v := range r.violations {
		if v.Severity == "critical" {
			return true
		}
	}
	return false
}
