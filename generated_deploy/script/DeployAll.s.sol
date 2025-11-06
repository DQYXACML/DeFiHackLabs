// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "forge-std/Script.sol";
import "./2024-02/ADC_exp_Deploy.s.sol";
import "./2024-02/AffineDeFi_exp_Deploy.s.sol";
import "./2024-02/BlueberryProtocol_exp_Deploy.s.sol";
import "./2024-02/CompoundUni_exp_Deploy.s.sol";
import "./2024-02/DeezNutz404_exp_Deploy.s.sol";
import "./2024-02/EGGX_exp_Deploy.s.sol";
import "./2024-02/GAIN_exp_Deploy.s.sol";
import "./2024-02/Game_exp_Deploy.s.sol";
import "./2024-02/Miner_exp_Deploy.s.sol";
import "./2024-02/PANDORA_exp_Deploy.s.sol";
import "./2024-02/ParticleTrade_exp_Deploy.s.sol";
import "./2024-02/RuggedArt_exp_Deploy.s.sol";
import "./2024-02/Seneca_exp_Deploy.s.sol";
import "./2024-02/SwarmMarkets_exp_Deploy.s.sol";
import "./2024-02/Zoomer_exp_Deploy.s.sol";
import "./2024-03/BBT_exp_Deploy.s.sol";
import "./2024-03/CGT_exp_Deploy.s.sol";
import "./2024-03/Juice_exp_Deploy.s.sol";
import "./2024-03/LavaLending_exp_Deploy.s.sol";
import "./2024-03/MO_exp_Deploy.s.sol";
import "./2024-03/Paraswap_exp_Deploy.s.sol";
import "./2024-03/SSS_exp_Deploy.s.sol";
import "./2024-03/UnizenIO2_exp_Deploy.s.sol";
import "./2024-03/UnizenIO_exp_Deploy.s.sol";
import "./2024-03/Woofi_exp_Deploy.s.sol";

/**
 * @title DeployAll
 * @notice 部署所有攻击事件的状态
 * @dev 自动生成的总控脚本
 *
 * 统计信息:
 * - 总事件数: 25
 * - 生成时间: 2025-11-03T14:11:56.233359
 */
contract DeployAll is Script {
    function run() external {
        console.log(unicode"开始部署所有攻击状态...");
        console.log(unicode"总计: 25 个事件");
        console.log("");

        new DeployADC().run();
        new DeployAffineDeFi().run();
        new DeployBlueberryProtocol().run();
        new DeployCompoundUni().run();
        new DeployDeezNutz404().run();
        new DeployEGGX().run();
        new DeployGAIN().run();
        new DeployGame().run();
        new DeployMiner().run();
        new DeployPANDORA().run();
        new DeployParticleTrade().run();
        new DeployRuggedArt().run();
        new DeploySeneca().run();
        new DeploySwarmMarkets().run();
        new DeployZoomer().run();
        new DeployBBT().run();
        new DeployCGT().run();
        new DeployJuice().run();
        new DeployLavaLending().run();
        new DeployMO().run();
        new DeployParaswap().run();
        new DeploySSS().run();
        new DeployUnizenIO2().run();
        new DeployUnizenIO().run();
        new DeployWoofi().run();

        console.log("");
        console.log(unicode"所有部署完成！");
    }
}
