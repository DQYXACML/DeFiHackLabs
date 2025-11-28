// SPDX-License-Identifier: UNLICENSED
pragma solidity 0.8.20;

import {IUniV3Pool} from "./interfaces/IUniV3Pool.sol";
import {IUniV3Callback} from "./interfaces/IUniV3Callback.sol";
import {LiquidityAmounts} from "./libraries/LiquidityAmounts.sol";
import {FeeMath} from "./libraries/FeeMath.sol";
import {Math} from "./libraries/Math.sol";
import {Oracle} from "./libraries/Oracle.sol";
import {FullMath} from "./libraries/FullMath.sol";
import {TickMath} from "./libraries/TickMath.sol";
import {ERC20} from "solmate/tokens/ERC20.sol";
import {SafeTransferLib} from "solmate/utils/SafeTransferLib.sol";
import {OwnableUpgradeable} from "@openzeppelin/contracts-upgradeable/access/OwnableUpgradeable.sol";

/**
 * @notice Liquidity management functions for Uniswap V3.
 * Adds liquidity directly to the pool instead of using the Uniswap V3 manager.
 * (Adding liquidity via the Uniswap V3 manager allows donations - we want to avoid this).
 * It prevents donations of any kinds to the wrapper. If funds are sent directly to this contract
 * they would not be included in its total assets count.
 */
/// @custom:oz-upgrades-from src/UniV3/LiquidityProviderBaseOld.sol:LiquidityProviderBaseOld
abstract contract LiquidityProviderBase is OwnableUpgradeable, IUniV3Callback {
    using SafeTransferLib for ERC20;
    using Oracle for IUniV3Pool;

    /// @notice The pool the contract is providing liquidity to.
    IUniV3Pool public pool;
    /// @notice Token0 of the pool.
    ERC20 public token0;
    /// @notice Token1 of the pool.
    ERC20 public token1;

    /// @notice Lower bound of the liquidity range.
    int24 public tickLower;
    /// @notice Upper bound of the liquidity range.
    int24 public tickUpper;
    /// @notice Keeps internal track of the added liquidity.
    uint128 public totalLiquidity;
    /// @notice Internal track of the token0 balance.
    uint256 public balance0;
    /// @notice Internal track of the token1 balance.
    uint256 public balance1;
    /// @notice Last time the liquidity was compounded.
    uint32 public lastCompoundTime;
    /// @notice Max fees APR based on the current liquidity and last compound time.
    uint256 public maxAprPercent;
    /// @notice Max slippage in basis points.
    uint256 public maxSlippageBps;
    /// @notice Slippage moving average duration in seconds.
    uint32 public slippageMA;
    /// @notice Pause flag.
    bool public paused;
    // Storage gap.
    uint256[50] internal __gapBase;

    event SetMaxAprPercent(uint256 maxAprPercent);
    event SetMaxSlippageBps(uint256 maxSlippageBps);
    event SetSlippageMovingAverage(uint32 slippageMovingAverage);
    event SetPause(bool paused);
    event BalanceChange(int256 balance0, int256 balance1);

    error Paused();
    error VolatilePrice();
    error Unauthorized();
    error InvalidTicks();

    /// @notice On-chain slippage protection.
    modifier stablePrice() {
        (, int24 currentTick,,,,,) = pool.slot0();
        int24 tickMovingAverage = getMovingAverage(slippageMA);
        if (Math.diff(currentTick, tickMovingAverage) > maxSlippageBps) revert VolatilePrice();
        _;
    }

    /// @notice Paused modifier.
    modifier notPaused() {
        if (paused) revert Paused();
        _;
    }

    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() {
        _disableInitializers();
    }

    function __Base_init(address uniV3Pool, int24 _tickLower, int24 _tickUpper) public onlyInitializing {
        __Ownable_init(msg.sender);
        pool = IUniV3Pool(uniV3Pool);
        token0 = ERC20(IUniV3Pool(uniV3Pool).token0());
        token1 = ERC20(IUniV3Pool(uniV3Pool).token1());
        int24 tickSpacing = IUniV3Pool(uniV3Pool).tickSpacing();
        if (_tickLower % tickSpacing != 0 || _tickUpper % tickSpacing != 0) revert InvalidTicks();
        tickLower = _tickLower;
        tickUpper = _tickUpper;
        maxAprPercent = 300;
        maxSlippageBps = 25;
        slippageMA = 1 minutes;
    }

    /// @notice Returns the contract's position in the pool.
    /// @dev We want to rely on the internal liquidity count as liquidity can be added to
    /// the pool directly. It should not be counted towards the contract's liquidity.
    function getPosition()
        public
        view
        returns (
            uint128 liquidity,
            uint256 feeGrowthInside0LastX128,
            uint256 feeGrowthInside1LastX128,
            uint128 tokensOwed0,
            uint128 tokensOwed1
        )
    {
        bytes32 key = keccak256(abi.encodePacked(address(this), tickLower, tickUpper));
        return pool.positions(key);
    }

    /// @notice Current price in the pool.
    function getCurrentPrice() public view returns (uint160 sqrtRatioX96) {
        (sqrtRatioX96,,,,,,) = pool.slot0();
    }

    /// @notice Range where the contract is currently providing liquidity.
    function getRangePrices() public view returns (uint160 sqrtRatioAX96, uint160 sqrtRatioBX96) {
        sqrtRatioAX96 = TickMath.getSqrtRatioAtTick(tickLower);
        sqrtRatioBX96 = TickMath.getSqrtRatioAtTick(tickUpper);
    }

    /// @notice Wether the current price is within the contract's liquidity range.
    function inRange() public view returns (bool) {
        uint160 sqrtRatioX96 = getCurrentPrice();
        (uint160 sqrtRatioAX96, uint160 sqrtRatioBX96) = getRangePrices();
        return sqrtRatioAX96 < sqrtRatioX96 && sqrtRatioX96 < sqrtRatioBX96;
    }

    /// @notice Calculates the moving average price for the given duration.
    function getMovingAverage(uint32 duration) public view returns (int24 tick) {
        return pool.getMovingAverage(duration);
    }

    /// @notice Calculates token amounts for the given liquidity, current price and contract's liquidity range.
    function getAmountsForLiquidity(uint128 liquidity) public view returns (uint256 amount0, uint256 amount1) {
        return getAmountsForLiquidity(liquidity, getCurrentPrice());
    }

    /// @notice Calculates token amounts for the given liquidity and price.
    function getAmountsForLiquidity(uint128 liquidity, uint160 price)
        public
        view
        returns (uint256 amount0, uint256 amount1)
    {
        (uint160 sqrtRatioAX96, uint160 sqrtRatioBX96) = getRangePrices();
        (amount0, amount1) = LiquidityAmounts.getAmountsForLiquidity(price, sqrtRatioAX96, sqrtRatioBX96, liquidity);
    }

    /// @notice Calculates trading fees that can be claimed.
    function getUnclaimedFees() public view returns (uint256 amount0, uint256 amount1) {
        (, uint256 feeGrowthInside0Last, uint256 feeGrowthInside1Last,,) = getPosition();
        (, int24 currentTick,,,,,) = pool.slot0();
        (,, uint256 l_feeGrowthOutside0, uint256 l_feeGrowthOutside1,,,,) = pool.ticks(tickLower);
        (,, uint256 u_feeGrowthOutside0, uint256 u_feeGrowthOutside1,,,,) = pool.ticks(tickUpper);
        (uint256 feeGrowthInside0, uint256 feeGrowthInside1) = FeeMath.getFeeGrowthInside(
            tickLower,
            tickUpper,
            currentTick,
            pool.feeGrowthGlobal0X128(),
            pool.feeGrowthGlobal1X128(),
            l_feeGrowthOutside0,
            l_feeGrowthOutside1,
            u_feeGrowthOutside0,
            u_feeGrowthOutside1
        );
        (amount0, amount1) = FeeMath.getPendingFees(
            totalLiquidity, feeGrowthInside0Last, feeGrowthInside1Last, feeGrowthInside0, feeGrowthInside1
        );
        return _limitFees(amount0, amount1);
    }

    /// @notice Calculate the amount of liquidity that can be directly added to the current position given two asset amounts.
    function mintLiquidityPreview(uint256 amount0, uint256 amount1)
        public
        view
        returns (uint128 liquidity, bool token1Remains, uint256 amountRemaining)
    {
        uint160 sqrtRatioX96 = getCurrentPrice();
        (uint160 sqrtRatioAX96, uint160 sqrtRatioBX96) = getRangePrices();
        return LiquidityAmounts.getLiquidityForAmounts(sqrtRatioX96, sqrtRatioAX96, sqrtRatioBX96, amount0, amount1);
    }

    /// @notice Returns the amount we need to swap to add the maximum amount of liquidity, starting with only one asset.
    function onesidedMintPreview(uint256 startingAmount, bool isToken0) public view returns (uint256 amountToSwap) {
        (uint160 sqrtRatioAX96, uint160 sqrtRatioBX96) = getRangePrices();
        uint160 sqrtRatioX96 = getCurrentPrice();
        return LiquidityAmounts.onesidedMintPreview(
            sqrtRatioX96, sqrtRatioAX96, sqrtRatioBX96, pool.liquidity(), startingAmount, isToken0
        );
    }

    /// @notice Returns the amount we need to swap to add the maximum amount of liquidity, starting with two assets.
    function mintMaxLiquidityPreview(uint256 amount0, uint256 amount1)
        public
        view
        returns (uint256 amountToSwap, bool zeroForOne)
    {
        uint160 sqrtRatioX96 = getCurrentPrice();
        (uint160 sqrtRatioAX96, uint160 sqrtRatioBX96) = getRangePrices();
        uint128 liquidity = pool.liquidity();
        return LiquidityAmounts.maxMintPreview(sqrtRatioX96, sqrtRatioAX96, sqrtRatioBX96, liquidity, amount0, amount1);
    }

    /// @notice Sets the maximum fee APR.
    function setMaxPoolApr(uint256 _maxAprPercent) external onlyOwner {
        maxAprPercent = _maxAprPercent;
        emit SetMaxAprPercent(_maxAprPercent);
    }

    /// @notice Sets the pause state.
    function setPause(bool _paused) external onlyOwner {
        paused = _paused;
        emit SetPause(_paused);
    }

    /// @notice Sets the maximum slippage protection deviation.
    function setMaxSlippage(uint256 _maxSlippageBps) external onlyOwner {
        maxSlippageBps = _maxSlippageBps;
        emit SetMaxSlippageBps(_maxSlippageBps);
    }

    /// @notice Sets the slippage protection moving average window.
    function setSlippageMovingAverage(uint32 _movingAverage) external onlyOwner {
        slippageMA = _movingAverage;
        emit SetSlippageMovingAverage(_movingAverage);
    }

    /// @notice Withdraws the excess token balance to the owner.
    function skim(ERC20 token) external {
        uint256 balance = token.balanceOf(address(this));
        if (token == token0) {
            token0.safeTransfer(owner(), balance - balance0);
        } else if (token == token1) {
            token1.safeTransfer(owner(), balance - balance1);
        } else {
            token.safeTransfer(owner(), balance);
        }
    }

    /// @notice Limits the fees to the maximum APR.
    /// @dev This is done so the pool's lp token value cannot be easily inflated.
    function _limitFees(uint256 totalFees0, uint256 totalFees1)
        internal
        view
        returns (uint256 amount0, uint256 amount1)
    {
        (uint256 invested0, uint256 invested1) = getAmountsForLiquidity(totalLiquidity);
        uint256 passedTime = 1 + (block.timestamp - lastCompoundTime);
        /// @dev Calculating APR as a ratio of fees / liquidity is a rough estimate for the APR as it depends on
        /// the ratio of assets. We only limit fees when both token0 and token1 fees overflow.
        uint256 max0 = (invested0 * maxAprPercent / 100) * passedTime / 365 days;
        uint256 max1 = (invested1 * maxAprPercent / 100) * passedTime / 365 days;
        if (totalFees0 > max0 && totalFees1 > max1) {
            return (max0, max1);
        } else {
            return (totalFees0, totalFees1);
        }
    }

    /// @notice Adds liquidity to the pool. Assets are taken from sender.
    function _addLiquidity(uint128 liquidity, address sender)
        internal
        notPaused
        returns (uint256 amount0, uint256 amount1)
    {
        if (liquidity == 0) return (0, 0);
        (amount0, amount1) = pool.mint(address(this), tickLower, tickUpper, liquidity, abi.encode(sender));
        totalLiquidity += liquidity;
    }

    /// @notice Removes liquidity from the pool (including the fees).
    /// @dev Call with liquidityAmount = 0 to collect all fees earned.
    function _removeLiquidity(uint128 liquidity, address recipient)
        internal
        notPaused
        returns (uint256 amount0, uint256 amount1)
    {
        pool.burn(tickLower, tickUpper, liquidity);
        totalLiquidity -= liquidity;
        (amount0, amount1) = pool.collect(recipient, tickLower, tickUpper, type(uint128).max, type(uint128).max);
        if (recipient == address(this)) {
            balance0 += amount0;
            balance1 += amount1;
            emit BalanceChange(int256(balance0), int256(balance1));
        }
    }

    /// @notice Collects all fees earned from the pool.
    function _collectFees() internal notPaused returns (uint256 amount0, uint256 amount1) {
        pool.burn(tickLower, tickUpper, 0);
        (amount0, amount1) = pool.collect(address(this), tickLower, tickUpper, type(uint128).max, type(uint128).max);
        (amount0, amount1) = _limitFees(amount0, amount1);
        balance0 += amount0;
        balance1 += amount1;
        emit BalanceChange(int256(balance0), int256(balance1));
    }

    /// @notice Collects the fees and adds liquidity back to the pool.
    function _compound() internal notPaused returns (uint256 amount0, uint256 amount1, uint128 liquidityAdded) {
        if (totalLiquidity == 0 || lastCompoundTime == block.timestamp) return (0, 0, 0);
        _collectFees();
        lastCompoundTime = uint32(block.timestamp);
        (amount0, amount1, liquidityAdded) = _addMaxLiquidity();
    }

    /// @notice Adds whatever liquidity can be directly added to the pool.
    function _addAvailableLiquidity() internal returns (uint256 amount0, uint256 amount1, uint128 liquidityAdded) {
        (liquidityAdded,,) = mintLiquidityPreview(balance0, balance1);
        (amount0, amount1) = _addLiquidity(liquidityAdded, address(this));
    }

    /// @notice Adds the maximum amount of liquidity possible to the pool.
    /// @dev The calling function should add some from of slippage protection.
    function _addMaxLiquidity() internal returns (uint256 amount0, uint256 amount1, uint128 liquidityAdded) {
        uint160 sqrtRatioX96 = getCurrentPrice();
        (uint160 sqrtRatioAX96, uint160 sqrtRatioBX96) = getRangePrices();
        uint128 liquidity = pool.liquidity();
        (uint256 amountToSwap, bool zeroForOne) =
            LiquidityAmounts.maxMintPreview(sqrtRatioX96, sqrtRatioAX96, sqrtRatioBX96, liquidity, balance0, balance1);
        _swap(zeroForOne, amountToSwap, 0, address(this), address(this));
        sqrtRatioX96 = getCurrentPrice();
        (liquidityAdded,,) =
            LiquidityAmounts.getLiquidityForAmounts(sqrtRatioX96, sqrtRatioAX96, sqrtRatioBX96, balance0, balance1);
        (amount0, amount1) = _addLiquidity(liquidityAdded, address(this));
    }

    /// @notice Swaps one token for another.
    function _swap(bool zeroForOne, uint256 amountIn, uint256 minimumAmountOut, address sender, address recipient)
        internal
        notPaused
        returns (uint256 amountOut)
    {
        if (amountIn == 0) return 0;
        (int256 a, int256 b) = pool.swap(
            recipient,
            zeroForOne,
            int256(amountIn),
            zeroForOne ? TickMath.MIN_SQRT_RATIO + 1 : TickMath.MAX_SQRT_RATIO - 1,
            abi.encode(sender)
        );
        if (zeroForOne) {
            amountOut = uint256(-b);
            if (recipient == address(this)) balance1 += amountOut;
        } else {
            amountOut = uint256(-a);
            if (recipient == address(this)) balance0 += amountOut;
        }
        require(amountOut >= minimumAmountOut);
    }

    /// @notice Transfers funds to the uniswap pool when minting, from address(this) or from the user.
    function uniswapV3MintCallback(uint256 amount0Owed, uint256 amount1Owed, bytes calldata data) external {
        if (msg.sender != address(pool)) revert Unauthorized();
        address sender = abi.decode(data, (address));
        if (sender == address(this)) {
            token0.safeTransfer(msg.sender, amount0Owed);
            token1.safeTransfer(msg.sender, amount1Owed);
            balance0 -= amount0Owed;
            balance1 -= amount1Owed;
        } else {
            /// @dev In the case of zapIn the wrapper will have some balance of one of the tokens.
            /// We need to use up this local balance and then transfer the rest from the user.
            uint256 send0 = Math.min(balance0, amount0Owed);
            if (send0 > 0) {
                token0.safeTransfer(msg.sender, send0);
                amount0Owed -= send0;
                balance0 -= send0;
            }
            uint256 send1 = Math.min(balance1, amount1Owed);
            if (send1 > 0) {
                token1.safeTransfer(msg.sender, send1);
                amount1Owed -= send1;
                balance1 -= send1;
            }
            emit BalanceChange(int256(send0), int256(send1));
            token0.safeTransferFrom(sender, msg.sender, amount0Owed);
            token1.safeTransferFrom(sender, msg.sender, amount1Owed);
        }
    }

    /// @notice Transfers funds to the uniswap pool when swapping, from address(this) or from the user.
    function uniswapV3SwapCallback(int256 amount0Delta, int256 amount1Delta, bytes calldata data) external {
        if (msg.sender != address(pool)) revert Unauthorized();
        address sender = abi.decode(data, (address));
        if (sender == address(this)) {
            if (amount0Delta > 0) {
                token0.safeTransfer(msg.sender, uint256(amount0Delta));
                balance0 -= uint256(amount0Delta);
                emit BalanceChange(-amount0Delta, 0);
            } else if (amount1Delta > 0) {
                token1.safeTransfer(msg.sender, uint256(amount1Delta));
                balance1 -= uint256(amount1Delta);
                emit BalanceChange(0, -amount1Delta);
            }
        } else {
            if (amount0Delta > 0) {
                token0.safeTransferFrom(sender, msg.sender, uint256(amount0Delta));
            } else if (amount1Delta > 0) {
                token1.safeTransferFrom(sender, msg.sender, uint256(amount1Delta));
            }
        }
    }
}
