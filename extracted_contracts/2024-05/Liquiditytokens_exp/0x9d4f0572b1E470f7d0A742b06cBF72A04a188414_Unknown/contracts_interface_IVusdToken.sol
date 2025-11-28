// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IVusdToken {
    function balanceOf(address account) external view returns (uint256);
    function burn(uint256 amount, bytes calldata data) external;
    function burnFrom(address account, uint256 amount) external;
    function mint(address to, uint256 amount) external;
}