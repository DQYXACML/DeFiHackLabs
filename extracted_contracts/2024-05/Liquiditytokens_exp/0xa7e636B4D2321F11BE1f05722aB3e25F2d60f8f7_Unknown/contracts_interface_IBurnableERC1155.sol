// contracts/IBurnableERC1155.sol
// SPDX-License-Identifier: MIT

pragma solidity 0.8.20;

interface IBurnableERC1155 {
    function burn(address account, uint256 id, uint256 value) external;
    function burnFrom(address account, uint256 id, uint256 value) external;
}