// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./interface/IDBridge.sol";
import "./interface/IERCToken.sol";
import "./interface/IVusdToken.sol";

contract VusdBurning {
    uint256 private _destinationChainId;    
    address private _bridgeAddress;

    constructor(
        uint256 destinationChainId_, 
        address bridgeAddress_
    ) {
        _destinationChainId = destinationChainId_;
        _bridgeAddress = bridgeAddress_;
    }

    function bridge(
        address tokenAddress
    ) external {
        uint256 balance = IERCToken(tokenAddress).balanceOf(address(this));
        require(balance > 0, "VusdBurningBsc: !Zero balance");

        IERCToken(tokenAddress).approve(_bridgeAddress, balance);
        IDBridge(_bridgeAddress).deposit(
            _destinationChainId,
            tokenAddress,
            balance
        );
    }

    function withdraw(
        bytes32 bridgeId
    ) external payable {
        IDBridge(_bridgeAddress).withdraw{value: msg.value}(bridgeId);
    }

    function burn(
        address tokenAddress
    ) external {
        uint256 balance = IERCToken(tokenAddress).balanceOf(address(this));
        require(balance > 0, "VusdBurningBsc: !Zero balance");
        IERCToken(tokenAddress).burn(balance);
    }

    function burnVusd(
        address tokenAddress
    ) external {
        uint256 balance = IERCToken(tokenAddress).balanceOf(address(this));
        require(balance > 0, "VusdBurningBsc: !Zero balance");
        IVusdToken(tokenAddress).burn(balance, new bytes(0));
    }
}
