// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.10;

import "forge-std/Test.sol";

contract VerifyForkBehavior is Test {
    // ZongZi攻击交易
    bytes32 constant ATTACK_TX = hex"247f4b3dbde9d8ab95c9766588d80f8dae835129225775ebd05a6dd2c69cd79f";
    // 已知攻击发生在区块 37272888
    
    function testForkWithTxHash() public {
        // 使用交易哈希fork
        vm.createSelectFork("bsc", ATTACK_TX);
        
        uint256 forkedBlock = block.number;
        console.log("=== Fork with TxHash ===");
        console.log("Forked to block:", forkedBlock);
        console.log("Attack was in block: 37272888");
        
        // 预期: 应该fork到37272888(攻击交易所在区块)
        assertEq(forkedBlock, 37272888, "Should fork to the block containing the tx");
    }
    
    function testForkWithBlockNumber() public {
        // 对比: 使用区块号fork
        vm.createSelectFork("bsc", 37272888);
        
        uint256 forkedBlock = block.number;
        console.log("=== Fork with BlockNumber ===");
        console.log("Forked to block:", forkedBlock);
        assertEq(forkedBlock, 37272888);
    }
}
