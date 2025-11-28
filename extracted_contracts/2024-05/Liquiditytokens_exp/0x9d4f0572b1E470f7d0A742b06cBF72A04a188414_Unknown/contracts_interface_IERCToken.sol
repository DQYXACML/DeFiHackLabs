// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IERCToken {
    function balanceOf(address account) external view returns (uint256);
    function approve(address to, uint256 amount) external;
    function burn(uint256 amount) external;
}