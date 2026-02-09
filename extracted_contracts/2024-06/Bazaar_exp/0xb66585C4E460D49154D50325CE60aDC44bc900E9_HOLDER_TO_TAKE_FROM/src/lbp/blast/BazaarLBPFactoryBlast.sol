pragma solidity ^0.7.0;
pragma experimental ABIEncoderV2;

import {IVault} from "balancer-lbp-patch/v2-vault/contracts/interfaces/IVault.sol";
import {IERC20 as BalancerERC20} from "balancer-lbp-patch/v2-solidity-utils/contracts/openzeppelin/IERC20.sol";

import {IBlast} from "../../interfaces/blast/IBlast.sol";
import {BazaarManager} from "../../BazaarManager.sol";
import {BazaarLBPBlast} from "./BazaarLBPBlast.sol";
import {BazaarLBP} from "../BazaarLBP.sol";
import {BazaarLBPFactoryBase, LBPConfig} from "../BazaarLBPFactoryBase.sol";

contract BazaarLBPFactoryBlast is BazaarLBPFactoryBase {
    IBlast public immutable BLAST;

    constructor(IVault _vault, BazaarManager _manager, IBlast _blast)
        BazaarLBPFactoryBase(_vault, _manager, type(BazaarLBPBlast).creationCode)
    {
        BLAST = _blast;
        _blast.configureClaimableGas();
    }

    // @devs Deploys a derived `BazaarLBPBast` instance
    function _deployLBP(LBPConfig memory cfg) internal override returns (BazaarLBP) {
        uint256[] memory startWeights = new uint256[](2);
        startWeights[0] = cfg.startWeights[0];
        startWeights[1] = cfg.startWeights[1];

        uint256[] memory endWeights = new uint256[](2);
        endWeights[0] = cfg.endWeights[0];
        endWeights[1] = cfg.endWeights[1];

        BalancerERC20[] memory tokens = new BalancerERC20[](2);
        tokens[0] = BalancerERC20(address(cfg.tokens[0]));
        tokens[1] = BalancerERC20(address(cfg.tokens[1]));

        uint256 swapFee = manager.defaultSwapFeePercentage();
        return BazaarLBPBlast(
            _create(
                abi.encode(
                    vault,
                    "Bazaar LBP",
                    "BZR",
                    tokens,
                    startWeights,
                    endWeights,
                    cfg.startTime,
                    cfg.endTime,
                    swapFee,
                    BLAST
                )
            )
        );
    }

    function claimGas(uint256 minClaimRateBips) external onlyManager {
        BLAST.claimGasAtMinClaimRate(address(this), manager.feeCollector(), minClaimRateBips);
    }

    // @dev the factory is the owner of all created LBPs, thus must have its gas claimed by the factory
    function claimLBPsGas(BazaarLBPBlast[] calldata lbps, uint256 minClaimRateBips) external onlyManager {
        for (uint256 i = 0; i < lbps.length; i++) {
            require(getLBPData(lbps[i]).owner != address(0));
            BLAST.claimGasAtMinClaimRate(address(lbps[i]), manager.feeCollector(), minClaimRateBips);
        }
    }
}
