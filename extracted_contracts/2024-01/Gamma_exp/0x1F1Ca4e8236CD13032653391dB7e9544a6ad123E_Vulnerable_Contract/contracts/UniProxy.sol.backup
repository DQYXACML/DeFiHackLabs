/// SPDX-License-Identifier: BUSL-1.1

pragma solidity 0.7.6;
pragma abicoder v2;

import "./interfaces/IHypervisor.sol";
import "../@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {IRouter} from "./interfaces/IRouter.sol";

interface IClearing {

	function clearDeposit(
    uint256 deposit0,
    uint256 deposit1,
    address from,
    address to,
    address pos,
    uint256[4] memory minIn
  ) external view returns (bool cleared);

	function clearShares(
    address pos,
    uint256 shares
  ) external view returns (bool cleared);

  function getDepositAmount(
    address pos,
    address token,
    uint256 _deposit
  ) external view returns (uint256 amountStart, uint256 amountEnd);
}

/// @title UniProxy v1.2.3
/// @notice Proxy contract for hypervisor positions management
contract UniProxy is ReentrancyGuard {
    // 防火墙读取单槽位接口
    function extsload(bytes32 slot) external view returns (bytes32 value) {
        assembly {
            value := sload(slot)
        }
    }

    // 兼容接口: 与 ext/tools 读取保持一致
    function getStorageAt(bytes32 slot) external view returns (bytes32 value) {
        assembly {
            value := sload(slot)
        }
    }



	IClearing public clearance;
  address public owner;
    // 防火墙路由器（使用普通变量而非immutable，支持构造后设置，避免子类stack too deep）
    // ========== 防火墙存储槽位（ERC1967风格） ==========
    /**
     * @dev 防火墙路由器存储槽位
     * 计算方式: bytes32(uint256(keccak256('firewall.router.storage')) - 1)
     * 槽位值: 0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc
     *
     * 此槽位在极高的存储空间，不会与合约原有变量（slot 0-N）冲突
     * 参考: ERC1967 Proxy Standard
     */
    bytes32 private constant FIREWALL_ROUTER_SLOT =
        bytes32(uint256(keccak256('firewall.router.storage')) - 1);

    /**
     * @dev 获取防火墙路由器地址
     */
    function firewall() public view returns (IRouter) {
        bytes32 slot = FIREWALL_ROUTER_SLOT;
        address firewallAddress;
        assembly {
            firewallAddress := sload(slot)
        }
        return IRouter(firewallAddress);
    }

    // 防火墙保护修饰符
    modifier firewallProtected() {
        IRouter _firewall = firewall();
        if (address(_firewall) != address(0)) {
            _firewall.executeWithDetect(msg.data);
        }
        _;
    }

    /**
     * @dev 设置防火墙路由器地址（internal，供子类在构造函数中调用）
     */
    function _setFirewall(address _firewall) internal {
        bytes32 slot = FIREWALL_ROUTER_SLOT;
        assembly {
            sstore(slot, _firewall)
        }
        emit FirewallUpdated(_firewall);
    }

    /**
     * @dev 公开设置防火墙地址（仅在未设置时可调用，支持动态更新）
     */
    function setFirewall(address _firewall) external {
        require(msg.sender == owner || address(firewall()) == address(0), "Not authorized");
        require(_firewall != address(0), "Invalid firewall address");
        bytes32 slot = FIREWALL_ROUTER_SLOT;
        assembly {
            sstore(slot, _firewall)
        }
        emit FirewallUpdated(_firewall);
    }

    event FirewallUpdated(address indexed newFirewall);



  constructor(address _clearance) {
    owner = msg.sender;
		clearance = IClearing(_clearance);	
  }

  /// @notice Deposit into the given position
  /// @param deposit0 Amount of token0 to deposit
  /// @param deposit1 Amount of token1 to deposit
  /// @param to Address to receive liquidity tokens
  /// @param pos Hypervisor Address
  /// @param minIn min assets to expect in position during a direct deposit 
  /// @return shares Amount of liquidity tokens received
  function deposit(
    uint256 deposit0,
    uint256 deposit1,
    address to,
    address pos,
    uint256[4] memory minIn
  ) nonReentrant external firewallProtected returns (uint256 shares) {
    require(to != address(0), "to should be non-zero");
		require(clearance.clearDeposit(deposit0, deposit1, msg.sender, to, pos, minIn), "deposit not cleared");

		/// transfer assets from msg.sender and mint lp tokens to provided address 
		shares = IHypervisor(pos).deposit(deposit0, deposit1, to, msg.sender, minIn);
		require(clearance.clearShares(pos, shares), "shares not cleared");
  }

  /// @notice Get the amount of token to deposit for the given amount of pair token
  /// @param pos Hypervisor Address
  /// @param token Address of token to deposit
  /// @param _deposit Amount of token to deposit
  /// @return amountStart Minimum amounts of the pair token to deposit
  /// @return amountEnd Maximum amounts of the pair token to deposit
  function getDepositAmount(
    address pos,
    address token,
    uint256 _deposit
  ) public view returns (uint256 amountStart, uint256 amountEnd) {
		return clearance.getDepositAmount(pos, token, _deposit);
	}

	function transferClearance(address newClearance) external onlyOwner {
    require(newClearance != address(0), "newClearance should be non-zero");
		clearance = IClearing(newClearance);
	}

  function transferOwnership(address newOwner) external onlyOwner {
    require(newOwner != address(0), "newOwner should be non-zero");
    owner = newOwner;
  }

  modifier onlyOwner {
    require(msg.sender == owner, "only owner");
    _;
  }
}