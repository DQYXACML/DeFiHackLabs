// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.4.25;

interface IRouter {
    function executeWithDetect(bytes data) external returns (bool);
    function releaseWithDetect(bytes data) external;
}
