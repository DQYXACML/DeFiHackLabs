// SPDX-License-Identifier: MIT
pragma solidity 0.8.2;

import "./ConfirmedOwner.sol";
import "../interfaces/ReadWriteAccessControllerInterface.sol";
import "../interfaces/ReadWriteAccessControlledInterface.sol";

contract ReadWriteAccessControlled is ReadWriteAccessControlledInterface, ConfirmedOwner(msg.sender) {
  ReadWriteAccessControllerInterface internal s_accessController;

  function setAccessController(ReadWriteAccessControllerInterface _accessController) external override onlyOwner {
    require(address(_accessController) != address(s_accessController), "Access controller is already set");
    s_accessController = _accessController;
    emit AccessControllerSet(address(_accessController), msg.sender);
  }

  function getAccessController() external view override returns (ReadWriteAccessControllerInterface) {
    return s_accessController;
  }
}
