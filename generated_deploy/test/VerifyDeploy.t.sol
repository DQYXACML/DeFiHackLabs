// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "forge-std/Test.sol";
import "../script/2024-01/BarleyFinance_exp_Deploy.s.sol";

/**
 * @title VerifyDeployTest
 * @notice 验证部署脚本的测试
 */
contract VerifyDeployTest is Test {
    function testDeploy() public {
        // 执行部署
        DeployBarleyFinance deployer = new DeployBarleyFinance();
        deployer.run();

        // 验证攻击者地址余额
        address attacker = 0x7B3a6EFF1C9925e509C2b01A389238c1FCC462B6;
        uint256 expectedBalance = 1406062464485437940;
        assertEq(attacker.balance, expectedBalance, "Attacker balance mismatch");

        // 验证攻击合约代码已部署
        address attackContract = 0x356E7481B957bE0165D6751a49b4b7194AEf18D5;
        uint256 codeSize;
        assembly {
            codeSize := extcodesize(attackContract)
        }
        assertGt(codeSize, 0, "Attack contract not deployed");

        // 验证DAI合约代码已部署
        address dai = 0x6B175474E89094C44Da98b954EedeAC495271d0F;
        assembly {
            codeSize := extcodesize(dai)
        }
        assertGt(codeSize, 0, "DAI contract not deployed");

        console.log(unicode"部署验证成功！");
        console.log("Attacker balance:", attacker.balance);
        console.log("Attack contract size:", attackContract.code.length);
        console.log("DAI contract size:", dai.code.length);
    }
}
