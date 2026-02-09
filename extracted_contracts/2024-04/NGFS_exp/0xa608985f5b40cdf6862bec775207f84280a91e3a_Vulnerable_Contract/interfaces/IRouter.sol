// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.4;

interface IRouter {
    function executeWithDetect(bytes calldata data) external returns (bool);
    function releaseWithDetect(bytes calldata data) external;
}
