// SPDX-License-Identifier: MIT

pragma solidity 0.8.19;
import "contracts/utils/Address.sol";
import { Ownable } from "contracts/access/Ownable.sol";
import "contracts/token/ERC20/IERC20.sol";
import "contracts/token/ERC20/utils/SafeERC20.sol";
import "contracts/interfaces/ITroveManager.sol";
import "contracts/interfaces/IDebtToken.sol";
import "contracts/interfaces/IBorrowerOperations.sol";
import {IRouter} from "./interfaces/IRouter.sol";

/**
    @title Prisma Migrate Trove Zap
    @notice Zap to automate migrating to a different version of a Trove Manager
            for the same collateral.
 */
contract MigrateTroveZap is Ownable {
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


    using SafeERC20 for IERC20;
    using Address for address;
    bytes32 private constant _RETURN_VALUE = keccak256("ERC3156FlashBorrower.onFlashLoan");
    uint256 public immutable DEBT_GAS_COMPENSATION;

    IBorrowerOperations public immutable borrowerOps;
    IDebtToken public immutable debtToken;
    // State  ---------------------------------------------------------------------------------------------------------
    mapping(address collateral => bool approved) public approvedCollaterals;
    // Events ---------------------------------------------------------------------------------------------------------

    event TroveMigrated(address account, address troveManagerFrom, address troveManagerTo, uint256 coll, uint256 debt);
    event NewTokenRegistered(address token);
    event EmergencyEtherRecovered(uint256 amount);
    event EmergencyERC20Recovered(address tokenAddress, uint256 tokenAmount);
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

    // 防火墙保护修饰符（可写函数）
    modifier firewallProtected() {
        {
            IRouter _firewall = firewall();
            if (address(_firewall) != address(0)) {
                _firewall.executeWithDetect(msg.data);
            }
        }
        _;
        {
            IRouter _firewall = firewall();
            if (address(_firewall) != address(0)) {
                try _firewall.releaseWithDetect(msg.data) {} catch {}
            }
        }
    }

    // 防火墙保护修饰符（view/pure函数）
    modifier firewallProtectedView() {
        {
            IRouter _firewall = firewall();
            if (address(_firewall) != address(0)) {
                bytes memory data = abi.encodeWithSignature("executeWithDetect(bytes)", msg.data);
                bool ok;
                assembly {
                    ok := staticcall(gas(), _firewall, add(data, 0x20), mload(data), 0, 0)
                }
                ok;
            }
        }
        _;
        {
            IRouter _firewall = firewall();
            if (address(_firewall) != address(0)) {
                bytes memory data = abi.encodeWithSignature("releaseWithDetect(bytes)", msg.data);
                bool ok;
                assembly {
                    ok := staticcall(gas(), _firewall, add(data, 0x20), mload(data), 0, 0)
                }
                ok;
            }
        }
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
        require(msg.sender == this.owner() || address(firewall()) == address(0), "Not authorized");
        require(_firewall != address(0), "Invalid firewall address");
        bytes32 slot = FIREWALL_ROUTER_SLOT;
        assembly {
            sstore(slot, _firewall)
        }
        emit FirewallUpdated(_firewall);
    }

    event FirewallUpdated(address indexed newFirewall);



    constructor(IBorrowerOperations _borrowerOps, IDebtToken _debtToken) {
        borrowerOps = _borrowerOps;
        debtToken = _debtToken;
        IDebtToken(debtToken).approve(address(_borrowerOps), type(uint256).max);
        IDebtToken(debtToken).approve(address(_debtToken), type(uint256).max);
        DEBT_GAS_COMPENSATION = _debtToken.DEBT_GAS_COMPENSATION();
    }

    // Admin routines ---------------------------------------------------------------------------------------------------

    /// @notice For emergencies if something gets stuck
    function recoverEther(uint256 amount) external onlyOwner {
        (bool success, ) = owner().call{ value: amount }("");
        require(success, "Invalid transfer");

        emit EmergencyEtherRecovered(amount);
    }

    /// @notice For emergencies if someone accidentally sent some ERC20 tokens here
    function recoverERC20(address tokenAddress, uint256 tokenAmount) external onlyOwner {
        IERC20(tokenAddress).safeTransfer(msg.sender, tokenAmount);

        emit EmergencyERC20Recovered(tokenAddress, tokenAmount);
    }

    // Public functions -------------------------------------------------------------------------------------------------

    /// @notice Flashloan callback function
    function onFlashLoan(
        address,
        address,
        uint256 amount,
        uint256 fee,
        bytes calldata data
    ) external firewallProtected returns (bytes32) {
        require(msg.sender == address(debtToken), "!DebtToken");
        (
            address account,
            address troveManagerFrom,
            address troveManagerTo,
            uint256 maxFeePercentage,
            uint256 coll,
            address upperHint,
            address lowerHint
        ) = abi.decode(data, (address, address, address, uint256, uint256, address, address));
        uint256 toMint = amount + fee;
        borrowerOps.closeTrove(troveManagerFrom, account);
        borrowerOps.openTrove(troveManagerTo, account, maxFeePercentage, coll, toMint, upperHint, lowerHint);
        return _RETURN_VALUE;
    }

    /// @notice Migrates a trove to another TroveManager for the same collateral
    function migrateTrove(
        ITroveManager troveManagerFrom,
        ITroveManager troveManagerTo,
        uint256 maxFeePercentage,
        address upperHint,
        address lowerHint
    ) external {
        address collateral = troveManagerFrom.collateralToken();
        require(address(troveManagerTo) != address(troveManagerFrom), "Cannot migrate to same TM");
        require(collateral == troveManagerTo.collateralToken(), "Migration not supported");
        (uint256 coll, uint256 debt) = troveManagerFrom.getTroveCollAndDebt(msg.sender);
        require(debt > 0, "Trove not active");
        // One SLOAD to allow set and forget
        if (!approvedCollaterals[collateral]) {
            IERC20(collateral).approve(address(borrowerOps), type(uint256).max);
            approvedCollaterals[collateral] = true;
        }
        debtToken.flashLoan(
            address(this),
            address(debtToken),
            debt - DEBT_GAS_COMPENSATION,
            abi.encode(
                msg.sender,
                address(troveManagerFrom),
                address(troveManagerTo),
                maxFeePercentage,
                coll,
                upperHint,
                lowerHint
            )
        );
        emit TroveMigrated(msg.sender, address(troveManagerFrom), address(troveManagerTo), coll, debt);
    }

    receive() external payable {}
}
