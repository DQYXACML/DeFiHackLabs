// SPDX-License-Identifier: MIT
pragma solidity 0.8.2;

interface PairReadAccessControllerInterface {
  function hasGlobalAccess(address user) external view returns (bool);

  function hasPairAccess(
    address user,
    address base,
    address quote
  ) external view returns (bool);
}
