// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract JPY {

    function name() external pure returns (string memory) {
        return "ApolloX Japanese Yen";
    }

    function symbol() external pure returns (string memory) {
        return "JPY";
    }

    function decimals() external pure returns (uint8) {
        return 18;
    }
}