pragma solidity ^0.7.0;
pragma experimental ABIEncoderV2;

import {IERC20} from "openzeppelin-0.7/token/ERC20/IERC20.sol";
import {SafeERC20} from "openzeppelin-0.7/token/ERC20/SafeERC20.sol";

import {IVault, IAsset} from "balancer-lbp-patch/v2-vault/contracts/interfaces/IVault.sol";
import {FixedPoint} from "balancer-lbp-patch/v2-solidity-utils/contracts/math/FixedPoint.sol";
import {BaseSplitCodeFactory} from "balancer-lbp-patch/v2-solidity-utils/contracts/helpers/BaseSplitCodeFactory.sol";
import {Errors, _require} from "balancer-lbp-patch/v2-solidity-utils/contracts/helpers/BalancerErrors.sol";

import {BazaarManager} from "../BazaarManager.sol";
import {BazaarReceiptToken} from "./BazaarReceiptToken.sol";
import {BazaarLBP} from "./BazaarLBP.sol";

struct LBPConfig {
    IERC20[2] tokens;
    uint256[2] amounts;
    uint256[2] startWeights;
    uint256[2] endWeights;
    uint256 startTime;
    uint256 endTime;
    bool usingReceiptToken;
}

// @dev A factory that deploys BazaarLBPs. This is marked abstract such that factories can
//      be created for different derived types of `BazaarLBP` such as `BazaarLBPBlast` by
//      implementing `_deployLBP`.
abstract contract BazaarLBPFactoryBase is BaseSplitCodeFactory {
    // Balancer Reference
    IVault public vault;

    // Manager
    BazaarManager public manager;

    // Created LBPs
    struct LBPData {
        address owner;
        bool usingReceiptToken;
        uint256[2] initialLiquidity;
        IERC20[2] tokens;
    }

    // LBP-specific fee percentages
    uint256 private MAX_FEE_PERCENTAGE = FixedPoint.ONE / 10; // 10%

    struct LBPFeePercentages {
        bool enabled;
        uint256 swapPercentage;
        uint256 exitQuoteTokenPercentage;
    }

    mapping(BazaarLBP => LBPData) private lbpData;
    mapping(BazaarLBP => LBPFeePercentages) public lbpFeePercentages;

    // Events
    event LBPFeePercentagesChanged(
        BazaarLBP indexed lbp, uint256 newSwapFeePercentage, uint256 newExitQuoteTokenFeePercentage
    );
    event BazaarLBPCreated(
        BazaarLBP indexed lbp,
        IERC20[2] tokens,
        uint256[2] startWeights,
        uint256[2] endWeights,
        uint256 startTime,
        uint256 endTime
    );

    // Modifiers
    modifier onlyManager() {
        _require(manager.owner() == msg.sender, Errors.SENDER_NOT_ALLOWED);
        _;
    }

    modifier onlyLBPOwner(BazaarLBP lbp) {
        _require(lbpData[lbp].owner == msg.sender, Errors.CALLER_IS_NOT_LBP_OWNER);
        _;
    }

    modifier fromFactory(BazaarLBP lbp) {
        _require(lbpData[lbp].owner != address(0), Errors.INVALID_POOL_ID);
        _;
    }

    constructor(IVault _vault, BazaarManager _manager, bytes memory creationCode) BaseSplitCodeFactory(creationCode) {
        manager = _manager;
        vault = _vault;
    }

    /**
     * Factory Management
     */
    function setLBPFeePercentages(BazaarLBP lbp, uint256 swapPercentage, uint256 exitQuotePercentage)
        external
        fromFactory(lbp)
        onlyManager
    {
        _require(
            swapPercentage <= MAX_FEE_PERCENTAGE && exitQuotePercentage <= MAX_FEE_PERCENTAGE,
            Errors.SWAP_FEE_PERCENTAGE_TOO_HIGH
        );

        LBPFeePercentages storage fees = lbpFeePercentages[lbp];
        fees.enabled = true;
        fees.swapPercentage = swapPercentage;
        fees.exitQuoteTokenPercentage = exitQuotePercentage;

        // update the swap fee percentage for the LBP
        lbp.setSwapFeePercentage(swapPercentage);

        emit LBPFeePercentagesChanged(lbp, swapPercentage, exitQuotePercentage);
    }

    function getFees(BazaarLBP lbp) public view fromFactory(lbp) returns (uint256, uint256) {
        LBPFeePercentages memory fees = lbpFeePercentages[lbp];
        if (fees.enabled) return (fees.swapPercentage, fees.exitQuoteTokenPercentage);
        return manager.defaultFeePercentages();
    }

    /**
     * LBP Creation
     */
    function createLBP(LBPConfig memory cfg) external virtual returns (BazaarLBP lbp) {
        _require(cfg.startTime > block.timestamp && cfg.endTime > cfg.startTime, Errors.LOWER_GREATER_THAN_UPPER_TARGET);
        _require(cfg.amounts[0] > 0 && cfg.amounts[1] > 0, Errors.INSUFFICIENT_BALANCE);

        // Require 1 Quote Token & 1 Project Token
        _require(
            manager.isQuoteToken(address(cfg.tokens[0])) != manager.isQuoteToken(address(cfg.tokens[1])),
            Errors.INVALID_TOKEN
        );

        // Extract Liquidity into the factory
        SafeERC20.safeTransferFrom(cfg.tokens[0], msg.sender, address(this), cfg.amounts[0]);
        SafeERC20.safeTransferFrom(cfg.tokens[1], msg.sender, address(this), cfg.amounts[1]);

        // Setup Receipt Token if specified
        if (cfg.usingReceiptToken) {
            // Setup the receipt token. The factory is temporarily the owner to mint the initial supply
            uint256 projectTokenIndex = manager.isQuoteToken(address(cfg.tokens[0])) ? 1 : 0;
            address underlyingToken = address(cfg.tokens[projectTokenIndex]);
            BazaarReceiptToken receiptToken = new BazaarReceiptToken(address(this), underlyingToken, address(vault), address(this));

            // Mint Receipt Liquidity
            SafeERC20.safeIncreaseAllowance(
                cfg.tokens[projectTokenIndex], address(receiptToken), cfg.amounts[projectTokenIndex]
            );
            receiptToken.mint(cfg.amounts[projectTokenIndex]);

            // Replace the underlying token in the config
            cfg.tokens[projectTokenIndex] = IERC20(address(receiptToken));

            // Transfer ownership, as the LBP owner is responsible setting the claimable status
            receiptToken.transferOwnership(msg.sender);
        }

        // Ensure Ordering (Balancer LBP/Vault Requirement)
        if (cfg.tokens[0] > cfg.tokens[1]) {
            IERC20 token0 = cfg.tokens[0];
            uint256 amount0 = cfg.amounts[0];
            uint256 startWeight0 = cfg.startWeights[0];
            uint256 endWeight0 = cfg.endWeights[0];

            cfg.tokens[0] = cfg.tokens[1];
            cfg.amounts[0] = cfg.amounts[1];
            cfg.startWeights[0] = cfg.startWeights[1];
            cfg.endWeights[0] = cfg.endWeights[1];

            cfg.tokens[1] = token0;
            cfg.amounts[1] = amount0;
            cfg.startWeights[1] = startWeight0;
            cfg.endWeights[1] = endWeight0;
        }

        // Allow the Balancer Vault to extract the initial liquidity from the factory
        SafeERC20.safeIncreaseAllowance(cfg.tokens[0], address(vault), cfg.amounts[0]);
        SafeERC20.safeIncreaseAllowance(cfg.tokens[1], address(vault), cfg.amounts[1]);

        // Deploy the LBP
        lbp = BazaarLBP(_deployLBP(cfg));
        lbpData[lbp] = LBPData(msg.sender, cfg.usingReceiptToken, cfg.amounts, cfg.tokens);

        // Deposit liquidity into the created pool
        uint256[] memory amounts = new uint256[](2);
        amounts[0] = cfg.amounts[0];
        amounts[1] = cfg.amounts[1];

        IAsset[] memory assets = new IAsset[](2);
        assets[0] = IAsset(address(cfg.tokens[0]));
        assets[1] = IAsset(address(cfg.tokens[1]));

        bytes memory userData = abi.encode(0, amounts); // INIT JoinKind
        vault.joinPool(
            lbp.getPoolId(), address(this), address(this), IVault.JoinPoolRequest(assets, amounts, userData, false)
        );

        emit BazaarLBPCreated(lbp, cfg.tokens, cfg.startWeights, cfg.endWeights, cfg.startTime, cfg.endTime);
    }

    function getLBPData(BazaarLBP lbp) public view returns (LBPData memory) {
        return lbpData[lbp];
    }

    // @dev uses `_create` to deploy the LBP according to the creation code registered in the constructor
    function _deployLBP(LBPConfig memory cfg) internal virtual returns (BazaarLBP);

    /**
     * LBP Owner Operations
     */
    function setSwapEnabled(BazaarLBP lbp, bool enabled) external onlyLBPOwner(lbp) {
        lbp.setSwapEnabled(enabled);
    }

    // @dev `minAmountsOut` is provides the optionality to assert conditions on the exit. If the owner is exiting
    //      after the weight schedule has completed, then this is not useful as it would be a full exit in which a
    //      user can sandwich in some swaps. Passing zero's in this expected scenario is ok
    //
    // @notice Since we support only a full exit of the LBP, we do not have to worry about maintaining state of the
    //         collected swap fees and they are only processed once.
    function exitLBP(BazaarLBP lbp, address recipient, uint256[] memory minAmountsOut) external onlyLBPOwner(lbp) {
        uint256 bptBal = IERC20(address(lbp)).balanceOf(address(this));
        _require(bptBal > 0, Errors.POOL_NO_TOKENS);

        LBPData memory data = lbpData[lbp];
        uint256[2] memory balancesBeforeExit =
            [data.tokens[0].balanceOf(address(this)), data.tokens[1].balanceOf(address(this))];

        IAsset[] memory assets = new IAsset[](2);
        assets[0] = IAsset(address(data.tokens[0]));
        assets[1] = IAsset(address(data.tokens[1]));

        // Exit from the pool. Receipt is this proxy so that we can extract fees.
        bytes memory userData = abi.encode(1, bptBal); // EXACT_BPT_IN_FOR_TOKENS_OUT ExitKind
        vault.exitPool(
            lbp.getPoolId(),
            address(this),
            payable(address(this)),
            IVault.ExitPoolRequest(assets, minAmountsOut, userData, false)
        );

        // Compute exited funds and fees to extract
        uint256[2] memory balancesAfterExit =
            [data.tokens[0].balanceOf(address(this)), data.tokens[1].balanceOf(address(this))];
        uint256[2] memory withdrawnAmounts =
            [balancesAfterExit[0] - balancesBeforeExit[0], balancesAfterExit[1] - balancesBeforeExit[1]];
        uint256[2] memory feeAmounts = _computeFees(lbp, data, withdrawnAmounts);
        // Called to stop fee drainage attacks
        lbp.resetSwapFees();

        // Disperse funds to the recipient
        SafeERC20.safeTransfer(data.tokens[0], recipient, withdrawnAmounts[0] - feeAmounts[0]);
        SafeERC20.safeTransfer(data.tokens[1], recipient, withdrawnAmounts[1] - feeAmounts[1]);

        // Disperse fees
        address feeCollector = manager.feeCollector();
        SafeERC20.safeTransfer(data.tokens[0], feeCollector, feeAmounts[0]);
        SafeERC20.safeTransfer(data.tokens[1], feeCollector, feeAmounts[1]);
    }

    function _computeFees(BazaarLBP lbp, LBPData memory data, uint256[2] memory withdrawnAmounts)
        internal
        view
        returns (uint256[2] memory feeAmounts)
    {
        uint256[] memory swapFees = lbp.totalAccruedSwapFeeAmounts();
        feeAmounts[0] = swapFees[0];
        feeAmounts[1] = swapFees[1];

        uint256 quoteTokenIndex = manager.isQuoteToken(address(data.tokens[0])) ? 0 : 1;
        uint256 fundAmount = withdrawnAmounts[quoteTokenIndex] - swapFees[quoteTokenIndex];
        if (fundAmount > data.initialLiquidity[quoteTokenIndex]) {
            (, uint256 exitFee) = getFees(lbp);

            uint256 raisedAmount = fundAmount - data.initialLiquidity[quoteTokenIndex];
            feeAmounts[quoteTokenIndex] += FixedPoint.mulUp(raisedAmount, exitFee);
        }
    }
}
