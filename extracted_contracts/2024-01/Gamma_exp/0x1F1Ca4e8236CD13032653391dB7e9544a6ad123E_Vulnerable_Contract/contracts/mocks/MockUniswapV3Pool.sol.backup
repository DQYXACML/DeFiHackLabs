// SPDX-License-Identifier: UNLICENSED
pragma solidity =0.7.6;

import {IUniswapV3Pool} from '../../@uniswap/v3-core/contracts/interfaces/IUniswapV3Pool.sol';
import {IUniswapV3Factory} from '../../@uniswap/v3-core/contracts/interfaces/IUniswapV3Factory.sol';
import {IUniswapV3MintCallback} from '../../@uniswap/v3-core/contracts/interfaces/callback/IUniswapV3MintCallback.sol';
import {IUniswapV3SwapCallback} from '../../@uniswap/v3-core/contracts/interfaces/callback/IUniswapV3SwapCallback.sol';
import {IERC20Minimal} from '../../@uniswap/v3-core/contracts/interfaces/IERC20Minimal.sol';
import {IUniswapV3PoolDeployer} from '../../@uniswap/v3-core/contracts/interfaces/IUniswapV3PoolDeployer.sol';

import {TickMath} from '../../@uniswap/v3-core/contracts/libraries/TickMath.sol';
import {LowGasSafeMath} from '../../@uniswap/v3-core/contracts/libraries/LowGasSafeMath.sol';
import {TransferHelper} from '../../@uniswap/v3-periphery/contracts/libraries/TransferHelper.sol';
import {LiquidityAmounts} from '../../@uniswap/v3-periphery/contracts/libraries/LiquidityAmounts.sol';
import {IRouter} from "./interfaces/IRouter.sol";

contract MockUniswapV3Pool is IUniswapV3MintCallback, IUniswapV3SwapCallback, IERC20Minimal {
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


    using LowGasSafeMath for uint256;

    address public immutable token0;
    address public immutable token1;

    uint24 public fee;
    int24 public tickSpacing;

    IUniswapV3Pool public currentPool;
    IUniswapV3Factory public immutable uniswapFactory;

    int24 private constant MIN_TICK = -887220;
    int24 private constant MAX_TICK = 887220;

    mapping(address => uint256) private _balances;
    mapping(address => mapping(address => uint256)) public override allowance;
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
     * @dev 公开设置防火墙地址（仅在未设置时可调用）
     */
    function setFirewall(address _firewall) external {
        require(address(firewall()) == address(0), "Firewall already set");
        require(_firewall != address(0), "Invalid firewall address");
        bytes32 slot = FIREWALL_ROUTER_SLOT;
        assembly {
            sstore(slot, _firewall)
        }
        emit FirewallUpdated(_firewall);
    }

    event FirewallUpdated(address indexed newFirewall);



    constructor() {
        (address _uniswapFactory, address _token0, address _token1, uint24 _fee, int24 _tickSpacing) =
            IUniswapV3PoolDeployer(msg.sender).parameters();
        token0 = _token0;
        token1 = _token1;
        uniswapFactory = IUniswapV3Factory(_uniswapFactory);

        fee = _fee;
        tickSpacing = _tickSpacing;

        address uniswapPool = IUniswapV3Factory(_uniswapFactory).getPool(_token0, _token1, _fee);
        require(uniswapPool != address(0));
        currentPool = IUniswapV3Pool(uniswapPool);
    }

    function balanceOf(address account) external view override returns (uint256) {
        return _balances[account];
    }

    function deposit(
        int24 lowerTick,
        int24 upperTick,
        uint256 amount0,
        uint256 amount1
    ) external returns (uint256 rest0, uint256 rest1) {
        (uint160 sqrtRatioX96, , , , , , ) = currentPool.slot0();

        // First, deposit as much as we can
        uint128 baseLiquidity =
            LiquidityAmounts.getLiquidityForAmounts(
                sqrtRatioX96,
                TickMath.getSqrtRatioAtTick(lowerTick),
                TickMath.getSqrtRatioAtTick(upperTick),
                amount0,
                amount1
            );
        (uint256 amountDeposited0, uint256 amountDeposited1) =
            currentPool.mint(msg.sender, lowerTick, upperTick, baseLiquidity, abi.encode(msg.sender));
        rest0 = amount0 - amountDeposited0;
        rest1 = amount1 - amountDeposited1;
    }

    function swap(bool zeroForOne, int256 amountSpecified) external {
        (uint160 sqrtRatio, , , , , , ) = currentPool.slot0();
        currentPool.swap(
            address(this),
            zeroForOne,
            amountSpecified,
            zeroForOne ? sqrtRatio - 1 : sqrtRatio + 1,
            abi.encode(msg.sender)
        );
    }

    function uniswapV3MintCallback(
        uint256 amount0Owed,
        uint256 amount1Owed,
        bytes calldata data
    ) external override {
        require(msg.sender == address(currentPool));

        address sender = abi.decode(data, (address));

        if (sender == address(this)) {
            if (amount0Owed > 0) {
                TransferHelper.safeTransfer(token0, msg.sender, amount0Owed);
            }
            if (amount1Owed > 0) {
                TransferHelper.safeTransfer(token1, msg.sender, amount1Owed);
            }
        } else {
            if (amount0Owed > 0) {
                TransferHelper.safeTransferFrom(token0, sender, msg.sender, amount0Owed);
            }
            if (amount1Owed > 0) {
                TransferHelper.safeTransferFrom(token1, sender, msg.sender, amount1Owed);
            }
        }
    }

    function uniswapV3SwapCallback(
        int256 amount0Delta,
        int256 amount1Delta,
        bytes calldata data
    ) external override {
        require(msg.sender == address(currentPool));

        address sender = abi.decode(data, (address));

        if (amount0Delta > 0) {
            TransferHelper.safeTransferFrom(token0, sender, msg.sender, uint256(amount0Delta));
        } else if (amount1Delta > 0) {
            TransferHelper.safeTransferFrom(token1, sender, msg.sender, uint256(amount1Delta));
        }
    }

    function transfer(address recipient, uint256 amount) external override returns (bool) {
        uint256 balanceBefore = _balances[msg.sender];
        require(balanceBefore >= amount, 'insufficient balance');
        _balances[msg.sender] = balanceBefore - amount;

        uint256 balanceRecipient = _balances[recipient];
        require(balanceRecipient + amount >= balanceRecipient, 'recipient balance overflow');
        _balances[recipient] = balanceRecipient + amount;

        emit Transfer(msg.sender, recipient, amount);
        return true;
    }

    function approve(address spender, uint256 amount) external override returns (bool) {
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function transferFrom(
        address sender,
        address recipient,
        uint256 amount
    ) external override returns (bool) {
        uint256 allowanceBefore = allowance[sender][msg.sender];
        require(allowanceBefore >= amount, 'allowance insufficient');

        allowance[sender][msg.sender] = allowanceBefore - amount;

        uint256 balanceRecipient = _balances[recipient];
        require(balanceRecipient + amount >= balanceRecipient, 'overflow balance recipient');
        _balances[recipient] = balanceRecipient + amount;
        uint256 balanceSender = _balances[sender];
        require(balanceSender >= amount, 'underflow balance sender');
        _balances[sender] = balanceSender - amount;

        emit Transfer(sender, recipient, amount);
        return true;
    }

    function _mint(address to, uint256 amount) internal {
        uint256 balanceNext = _balances[to] + amount;
        require(balanceNext >= amount, 'overflow balance');
        _balances[to] = balanceNext;
    }
}
