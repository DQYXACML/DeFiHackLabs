// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract Euro {

    function name() external pure returns (string memory) {
        return "ApolloX Euro";
    }

    function symbol() external pure returns (string memory) {
        return "EUR";
    }

    function decimals() external pure returns (uint8) {
        return 18;
    }
}