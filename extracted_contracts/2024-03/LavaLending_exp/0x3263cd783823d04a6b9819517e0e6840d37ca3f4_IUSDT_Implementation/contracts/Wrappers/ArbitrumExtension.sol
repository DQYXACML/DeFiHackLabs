// SPDX-License-Identifier: Apache 2.0

pragma solidity 0.8.4;

import "../Tether/TetherToken.sol";
import "../Tether/EIP3009.sol";
import "../Tether/util/SignatureChecker.sol";

/*

   Copyright Tether.to 2020

   Author Will Harborne

   Licensed under the Apache License, Version 2.0
   http://www.apache.org/licenses/LICENSE-2.0

*/

interface IArbToken {
    /**
     * @notice should increase token supply by amount, and should (probably) only be callable by the L1 bridge.
     */
    function bridgeMint(address account, uint256 amount) external;
    /**
     * @notice should decrease token supply by amount, and should (probably) only be callable by the L1 bridge.
     */
    function bridgeBurn(address account, uint256 amount) external;

    /**
     * @return address of layer 1 token
     */
    function l1Address() external view returns (address);
}

abstract contract ArbitrumExtension is TetherToken, IArbToken {
  address internal l2Gateway;
  address public override l1Address;
}

abstract contract TetherTokenV2Arbitrum is ArbitrumExtension, EIP3009 {
    bytes32 internal constant _PERMIT_TYPEHASH =
        keccak256(
            "Permit(address owner,address spender,uint256 value,uint256 nonce,uint256 deadline)"
        );

    constructor () initializer {}

    function domainSeparator()
        internal
        view
        virtual
        override
        returns (bytes32)
    {
        return _domainSeparatorV4();
    }

    /**
     * The following applies to the following function and comments to that function:
     * 
     * SPDX-License-Identifier: Apache-2.0
     *
     * Copyright (c) 2023, Circle Internet Financial, LLC.
     *
     * Licensed under the Apache License, Version 2.0 (the "License");
     * you may not use this file except in compliance with the License.
     * You may obtain a copy of the License at
     *
     * http://www.apache.org/licenses/LICENSE-2.0
     * 
     * Unless required by applicable law or agreed to in writing, software
     * distributed under the License is distributed on an "AS IS" BASIS,
     * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
     * See the License for the specific language governing permissions and
     * limitations under the License.
     * 
     * ---------------------------------------------------------------------
     * 
     * Adapted by Tether.to 2024 for greater flexibility and reusability
     */
    function _permit(
        address owner_,
        address spender,
        uint256 value,
        uint256 deadline,
        bytes memory signature
    ) internal {
        require(block.timestamp <= deadline, "ERC20Permit: expired deadline");

        bytes32 structHash = keccak256(
            abi.encode(
                _PERMIT_TYPEHASH,
                owner_,
                spender,
                value,
                _useNonce(owner_),
                deadline
            )
        );

        bytes32 hash = _hashTypedDataV4(structHash);

        require(
            SignatureChecker.isValidSignatureNow(owner_, hash, signature),
            "EIP2612: invalid signature"
        );

        _approve(owner_, spender, value);
    }

    /**
     * @notice Update allowance with a signed permit
     * @param owner_       Token owner's address
     * @param spender     Spender's address
     * @param value       Amount of allowance
     * @param deadline    The time at which the signature expires (unix time)
     * @param v   signature component v
     * @param r   signature component r
     * @param s   signature component s
     */
    function permit(
        address owner_,
        address spender,
        uint256 value,
        uint256 deadline,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) public virtual override {
        _permit(owner_, spender, value, deadline, abi.encodePacked(r, s, v));
    }

    /**
     * The following applies to the following function and comments to that function:
     * 
     * SPDX-License-Identifier: Apache-2.0
     *
     * Copyright (c) 2023, Circle Internet Financial, LLC.
     *
     * Licensed under the Apache License, Version 2.0 (the "License");
     * you may not use this file except in compliance with the License.
     * You may obtain a copy of the License at
     *
     * http://www.apache.org/licenses/LICENSE-2.0
     * 
     * Unless required by applicable law or agreed to in writing, software
     * distributed under the License is distributed on an "AS IS" BASIS,
     * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
     * See the License for the specific language governing permissions and
     * limitations under the License.
     * 
     * ---------------------------------------------------------------------
     * 
     * Adapted by Tether.to 2024 for greater flexibility and reusability
     */

    /**
     * @notice Update allowance with a signed permit
     * @dev EOA wallet signatures should be packed in the order of r, s, v.
     * @param owner_       Token owner's address (Authorizer)
     * @param spender     Spender's address
     * @param value       Amount of allowance
     * @param deadline    The time at which the signature expires (unix time), or max uint256 value to signal no expiration
     * @param signature   Signature bytes signed by an EOA wallet or a contract wallet
     */
    function permit(
        address owner_,
        address spender,
        uint256 value,
        uint256 deadline,
        bytes memory signature
    ) external {
        _permit(owner_, spender, value, deadline, signature);
    }

    /**
     * The following applies to the following function and comments to that function:
     * 
     * SPDX-License-Identifier: Apache-2.0
     *
     * Copyright (c) 2023, Circle Internet Financial, LLC.
     *
     * Licensed under the Apache License, Version 2.0 (the "License");
     * you may not use this file except in compliance with the License.
     * You may obtain a copy of the License at
     *
     * http://www.apache.org/licenses/LICENSE-2.0
     * 
     * Unless required by applicable law or agreed to in writing, software
     * distributed under the License is distributed on an "AS IS" BASIS,
     * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
     * See the License for the specific language governing permissions and
     * limitations under the License.
     * 
     * ---------------------------------------------------------------------
     * 
     * Adapted by Tether.to 2024 for greater flexibility and reusability
     */

    /**
     * @notice Execute a transfer with a signed authorization
     * @param from          Payer's address (Authorizer)
     * @param to            Payee's address
     * @param value         Amount to be transferred
     * @param validAfter    The time after which this is valid (unix time)
     * @param validBefore   The time before which this is valid (unix time)
     * @param nonce         Unique nonce
     * @param v             v of the signature
     * @param r             r of the signature
     * @param s             s of the signature
     */
    function transferWithAuthorization(
        address from,
        address to,
        uint256 value,
        uint256 validAfter,
        uint256 validBefore,
        bytes32 nonce,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) public onlyNotBlocked {
        _transferWithAuthorizationValidityCheck(
            from,
            to,
            value,
            validAfter,
            validBefore,
            nonce,
            abi.encodePacked(r, s, v)
        );
        _transfer(from, to, value);
    }

    /**
     * The following applies to the following function and comments to that function:
     * 
     * SPDX-License-Identifier: Apache-2.0
     *
     * Copyright (c) 2023, Circle Internet Financial, LLC.
     *
     * Licensed under the Apache License, Version 2.0 (the "License");
     * you may not use this file except in compliance with the License.
     * You may obtain a copy of the License at
     *
     * http://www.apache.org/licenses/LICENSE-2.0
     * 
     * Unless required by applicable law or agreed to in writing, software
     * distributed under the License is distributed on an "AS IS" BASIS,
     * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
     * See the License for the specific language governing permissions and
     * limitations under the License.
     * 
     * ---------------------------------------------------------------------
     * 
     * Adapted by Tether.to 2024 for greater flexibility and reusability
     */

    /**
     * @notice Execute a transfer with a signed authorization
     * @dev EOA wallet signatures should be packed in the order of r, s, v.
     * @param from          Payer's address (Authorizer)
     * @param to            Payee's address
     * @param value         Amount to be transferred
     * @param validAfter    The time after which this is valid (unix time)
     * @param validBefore   The time before which this is valid (unix time)
     * @param nonce         Unique nonce
     * @param signature     Signature bytes signed by an EOA wallet or a contract wallet
     */
    function transferWithAuthorization(
        address from,
        address to,
        uint256 value,
        uint256 validAfter,
        uint256 validBefore,
        bytes32 nonce,
        bytes memory signature
    ) external onlyNotBlocked {
        _transferWithAuthorizationValidityCheck(
            from,
            to,
            value,
            validAfter,
            validBefore,
            nonce,
            signature
        );
        _transfer(from, to, value);
    }

    /**
     * The following applies to the following function and comments to that function:
     * 
     * SPDX-License-Identifier: Apache-2.0
     *
     * Copyright (c) 2023, Circle Internet Financial, LLC.
     *
     * Licensed under the Apache License, Version 2.0 (the "License");
     * you may not use this file except in compliance with the License.
     * You may obtain a copy of the License at
     *
     * http://www.apache.org/licenses/LICENSE-2.0
     * 
     * Unless required by applicable law or agreed to in writing, software
     * distributed under the License is distributed on an "AS IS" BASIS,
     * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
     * See the License for the specific language governing permissions and
     * limitations under the License.
     * 
     * ---------------------------------------------------------------------
     * 
     * Adapted by Tether.to 2024 for greater flexibility and reusability
     */

    /**
     * @notice Receive a transfer with a signed authorization from the payer
     * @dev This has an additional check to ensure that the payee's address
     * matches the caller of this function to prevent front-running attacks.
     * @param from          Payer's address (Authorizer)
     * @param to            Payee's address
     * @param value         Amount to be transferred
     * @param validAfter    The time after which this is valid (unix time)
     * @param validBefore   The time before which this is valid (unix time)
     * @param nonce         Unique nonce
     * @param v             v of the signature
     * @param r             r of the signature
     * @param s             s of the signature
     */
    function receiveWithAuthorization(
        address from,
        address to,
        uint256 value,
        uint256 validAfter,
        uint256 validBefore,
        bytes32 nonce,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) public onlyNotBlocked {
        _receiveWithAuthorizationValidityCheck(
            from,
            to,
            value,
            validAfter,
            validBefore,
            nonce,
            abi.encodePacked(r, s, v)
        );
        _transfer(from, to, value);
    }

    /**
     * The following applies to the following function and comments to that function:
     * 
     * SPDX-License-Identifier: Apache-2.0
     *
     * Copyright (c) 2023, Circle Internet Financial, LLC.
     *
     * Licensed under the Apache License, Version 2.0 (the "License");
     * you may not use this file except in compliance with the License.
     * You may obtain a copy of the License at
     *
     * http://www.apache.org/licenses/LICENSE-2.0
     * 
     * Unless required by applicable law or agreed to in writing, software
     * distributed under the License is distributed on an "AS IS" BASIS,
     * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
     * See the License for the specific language governing permissions and
     * limitations under the License.
     * 
     * ---------------------------------------------------------------------
     * 
     * Adapted by Tether.to 2024 for greater flexibility and reusability
     */

    /**
     * @notice Receive a transfer with a signed authorization from the payer
     * @dev This has an additional check to ensure that the payee's address
     * matches the caller of this function to prevent front-running attacks.
     * EOA wallet signatures should be packed in the order of r, s, v.
     * @param from          Payer's address (Authorizer)
     * @param to            Payee's address
     * @param value         Amount to be transferred
     * @param validAfter    The time after which this is valid (unix time)
     * @param validBefore   The time before which this is valid (unix time)
     * @param nonce         Unique nonce
     * @param signature     Signature bytes signed by an EOA wallet or a contract wallet
     */
    function receiveWithAuthorization(
        address from,
        address to,
        uint256 value,
        uint256 validAfter,
        uint256 validBefore,
        bytes32 nonce,
        bytes memory signature
    ) external onlyNotBlocked {
        _receiveWithAuthorizationValidityCheck(
            from,
            to,
            value,
            validAfter,
            validBefore,
            nonce,
            signature
        );
        _transfer(from, to, value);
    }

    uint256[48] private __gap;
}

interface IArbL2GatewayRouter {
  function outboundTransfer(
        address _l1Token,
        address _to,
        uint256 _amount,
        bytes calldata _data
    ) external payable returns (bytes memory);
}

contract ArbitrumExtensionV2 is TetherTokenV2Arbitrum {
  event LogSetOFTContract(address indexed oftContract);
  event Burn(address indexed from, uint256 amount); 
  error NotImplemented();
  event LogUpdateNameAndSymbol(string name, string symbol);

  address public constant USDT0_L1_LOCKBOX = 0x6C96dE32CEa08842dcc4058c14d3aaAD7Fa41dee;
  IArbL2GatewayRouter internal constant ARBITRUM_L2_GATEWAY_ROUTER = IArbL2GatewayRouter(0x5288c571Fd7aD117beA99bF60FE0846C4E84F933);

  bool internal isMigrating;

  function migrate(
    string memory _name,
    string memory _symbol,
    address _oftContract
  ) public {
    require(!isMigrating, "ALREADY_MIGRATED");
    isMigrating = true;

    require(_oftContract != address(0), "INVALID_OFT_CONTRACT");
    _updateNameAndSymbol(_name, _symbol);
    
    ARBITRUM_L2_GATEWAY_ROUTER.outboundTransfer(l1Address, USDT0_L1_LOCKBOX, totalSupply(), bytes(""));

    l2Gateway = _oftContract;
    l1Address = address(0);
    emit LogSetOFTContract(_oftContract);
  }

  string internal _newName;
  string internal _newSymbol;

  function oftContract() public view returns (address) {
    return l2Gateway;
  }

  modifier onlyAuthorizedSender() {
    require(msg.sender == l2Gateway, "Only OFT can call");
    _;
  }

  /**
  * @notice Mint tokens on L2. Callable path is L1Gateway depositToken (which handles L1 escrow), which triggers L2Gateway, which calls this
  * @param account recipient of tokens
  * @param amount amount of tokens minted
  */
  function bridgeMint(address account, uint256 amount) external virtual override onlyAuthorizedSender {
    revert NotImplemented(); 
  }

  /**
  * @notice Burn tokens on L2.
  * @dev only the token bridge can call this
  * @param account owner of tokens
  * @param amount amount of tokens burnt
  */
  function bridgeBurn(address account, uint256 amount) external virtual override onlyAuthorizedSender {
  }

  function mint(address _destination, uint256 _amount) public override onlyAuthorizedSender {
    _mint(_destination, _amount);
    emit Mint(_destination, _amount);
  }

  function burn(address _from, uint256 _amount) public onlyAuthorizedSender {
    _burn(_from, _amount);
    emit Burn(_from, _amount);
  }

  function setOFTContract(address _oftContract) external onlyOwner {
    l2Gateway = _oftContract;
    emit LogSetOFTContract(_oftContract);
  }

  /**
  * @dev The hash of the name parameter for the EIP712 domain.
  *
  * NOTE: This function reads from storage by default, but can be redefined to return a constant value if gas costs
  * are a concern.
  */
  function _EIP712NameHash() internal virtual override view returns (bytes32) {
    return keccak256(bytes(name()));
  }

  function _updateNameAndSymbol(string memory _name, string memory _symbol) internal {
    _newName = _name;
    _newSymbol = _symbol;
    emit LogUpdateNameAndSymbol(_name, _symbol);
  }

  function updateNameAndSymbol(string memory _name, string memory _symbol) public onlyOwner {
    _updateNameAndSymbol(_name, _symbol);
  }

  /**
  * @dev Returns the name of the token.
  */
  function name() public view virtual override returns (string memory) {
    return bytes(_newName).length == 0 ? super.name() : _newName;
  }

  /**
  * @dev Returns the symbol of the token, usually a shorter version of the
  * name.
  */
  function symbol() public view virtual override returns (string memory) {
    return bytes(_newSymbol).length == 0 ? super.symbol() : _newSymbol;
  }
}
