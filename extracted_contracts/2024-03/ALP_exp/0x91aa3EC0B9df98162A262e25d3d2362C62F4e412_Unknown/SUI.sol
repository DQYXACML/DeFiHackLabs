// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract SUI {

    function name() external pure returns (string memory) {
        return "ApolloX SUI";
    }

    function symbol() external pure returns (string memory) {
        return "SUI";
    }

    function decimals() external pure returns (uint8) {
        return 18;
    }
}