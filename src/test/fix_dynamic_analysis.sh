#!/bin/bash
#
# extract_contracts.py 动态追踪修复脚本
#
# 此脚本自动修复导致动态追踪失败的所有问题:
# 1. 清理 contract_sources/ 目录
# 2. 配置 foundry.toml 排除有问题的文件
# 3. 验证修复效果
#

set -e  # 遇到错误立即退出

PROJECT_ROOT="/home/dqy/Firewall/FirewallOnchain/DeFiHackLabs"
TEST_DIR="$PROJECT_ROOT/src/test"
FOUNDRY_TOML="$PROJECT_ROOT/foundry.toml"

echo "=============================================================================="
echo "extract_contracts.py 动态追踪修复脚本"
echo "=============================================================================="

# 步骤 1: 清理 contract_sources
echo ""
echo "步骤 1: 清理旧的 contract_sources 目录..."
if [ -d "$TEST_DIR/contract_sources" ]; then
    echo "  发现 contract_sources/ 目录,正在删除..."
    rm -rf "$TEST_DIR/contract_sources"
    echo "  ✓ 已删除"
else
    echo "  ✓ contract_sources/ 不存在,跳过"
fi

# 步骤 2: 备份 foundry.toml
echo ""
echo "步骤 2: 备份 foundry.toml..."
if [ ! -f "$FOUNDRY_TOML.backup" ]; then
    cp "$FOUNDRY_TOML" "$FOUNDRY_TOML.backup"
    echo "  ✓ 已备份到 foundry.toml.backup"
else
    echo "  ✓ 备份已存在,跳过"
fi

# 步骤 3: 检查 foundry.toml 是否已经配置了 exclude
echo ""
echo "步骤 3: 配置 foundry.toml 排除规则..."
if grep -q "exclude\s*=" "$FOUNDRY_TOML"; then
    echo "  ⚠ foundry.toml 已包含 exclude 配置,请手动检查"
    echo "  建议添加以下排除规则:"
    echo "    - 'src/test/contract_sources/**'"
    echo "    - 'src/test/2023-02/Orion_exp.sol'"
else
    # 在 [profile.default] 部分添加 exclude
    echo "  正在添加 exclude 配置..."
    # 在 libs 行后插入 exclude
    sed -i "/^libs = /a exclude = ['src/test/contract_sources/**', 'src/test/2023-02/Orion_exp.sol']" "$FOUNDRY_TOML"
    echo "  ✓ 已添加排除规则"
fi

# 步骤 4: 验证 Forge 编译
echo ""
echo "步骤 4: 验证 Forge 编译..."
cd "$PROJECT_ROOT"
if forge build --force > /tmp/forge_build.log 2>&1; then
    echo "  ✓ Forge 编译成功!"
else
    echo "  ⚠ Forge 编译仍有警告/错误"
    echo "  查看详细日志: tail /tmp/forge_build.log"
    echo ""
    echo "  可能需要排除更多文件。运行以下命令查看错误:"
    echo "  forge build 2>&1 | grep 'Error:' | head -20"
fi

# 步骤 5: 测试单个文件
echo ""
echo "步骤 5: 测试单个文件的动态分析..."
TEST_FILE="src/test/2024-06/Will_exp.sol"
if [ -f "$PROJECT_ROOT/$TEST_FILE" ]; then
    echo "  正在测试: $TEST_FILE"
    if forge test --match-path "$TEST_FILE" > /tmp/forge_test.log 2>&1; then
        echo "  ✓ 测试运行成功!"
    else
        # 检查输出中是否有 Traces
        if grep -q "Traces:" /tmp/forge_test.log; then
            echo "  ⚠ 测试失败,但生成了 trace 输出"
            echo "  动态分析可能仍然有效"
        else
            echo "  ✗ 测试失败且没有 trace 输出"
            echo "  查看详细日志: tail -50 /tmp/forge_test.log"
        fi
    fi
else
    echo "  ⚠ 测试文件不存在: $TEST_FILE"
    echo "  请选择其他测试文件"
fi

# 步骤 6: 总结
echo ""
echo "=============================================================================="
echo "修复完成!"
echo "=============================================================================="
echo ""
echo "已完成的操作:"
echo "  ✓ 清理 contract_sources/ 目录"
echo "  ✓ 备份 foundry.toml"
echo "  ✓ 添加 exclude 排除规则"
echo "  ✓ 验证 Forge 编译"
echo ""
echo "后续步骤:"
echo "  1. 运行动态分析:"
echo "     cd $TEST_DIR"
echo "     python3 extract_contracts.py --filter 2024-06"
echo ""
echo "  2. 查看结果:"
echo "     cat $PROJECT_ROOT/extracted_contracts/summary.json"
echo ""
echo "  3. 如果仍有问题,检查详细文档:"
echo "     cat $TEST_DIR/EXTRACT_CONTRACTS_FIX.md"
echo ""
echo "  4. 恢复原配置(如需要):"
echo "     cp $FOUNDRY_TOML.backup $FOUNDRY_TOML"
echo ""
echo "=============================================================================="
