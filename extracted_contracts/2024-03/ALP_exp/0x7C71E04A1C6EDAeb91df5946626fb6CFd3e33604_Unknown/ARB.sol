// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract ARB {

    function name() external pure returns (string memory) {
        return "ApolloX Arbitrum";
    }

    function symbol() external pure returns (string memory) {
        return "ARB";
    }

    function decimals() external pure returns (uint8) {
        return 18;
    }
}