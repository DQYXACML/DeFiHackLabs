// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";

contract ApproveProxy is Ownable {
    mapping(address => bool) public operators;

    error NotOperator();

    constructor() Ownable(msg.sender) {}

    function addOperator(address operator) public onlyOwner {
        operators[operator] = true;
    }

    function removeOperator(address operator) public onlyOwner {
        operators[operator] = false;
    }

    function claim(address token, address from, address to, uint256 amount) public {
        if (operators[msg.sender] == false) revert NotOperator();
        IERC20(token).transferFrom(from, to, amount);
    }
}
