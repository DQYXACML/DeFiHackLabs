// SPDX-License-Identifier: MIT
pragma solidity 0.8.2;

import "./ConfirmedOwner.sol";
import "../interfaces/PairReadAccessControlledInterface.sol";

contract PairReadAccessControlled is PairReadAccessControlledInterface, ConfirmedOwner(msg.sender) {
  PairReadAccessControllerInterface internal s_accessController;

  function setAccessController(PairReadAccessControllerInterface _accessController) external override onlyOwner {
    require(address(_accessController) != address(s_accessController), "Access controller is already set");
    s_accessController = _accessController;
    emit PairAccessControllerSet(address(_accessController), msg.sender);
  }

  function getAccessController() external view override returns (PairReadAccessControllerInterface) {
    return s_accessController;
  }
}
