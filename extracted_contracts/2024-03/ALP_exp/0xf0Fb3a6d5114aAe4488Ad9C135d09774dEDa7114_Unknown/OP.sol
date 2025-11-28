// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract OP {

    function name() external pure returns (string memory) {
        return "ApolloX OP";
    }

    function symbol() external pure returns (string memory) {
        return "OP";
    }

    function decimals() external pure returns (uint8) {
        return 18;
    }
}