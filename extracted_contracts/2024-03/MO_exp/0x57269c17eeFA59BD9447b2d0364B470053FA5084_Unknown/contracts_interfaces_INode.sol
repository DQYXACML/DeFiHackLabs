// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

interface INode {
    function nodes(address user) external view returns (bool);
}
