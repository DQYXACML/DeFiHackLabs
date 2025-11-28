// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "AggregatorV3Interface.sol";
import "Address.sol";
import "DefaultAccess.sol";
import "IOracleConnector.sol";

contract OracleChainlink is DefaultAccess, IOracleConnector {
    using EnumerableSet for EnumerableSet.AddressSet;
    using Address for address;

    mapping(address => address) public usdPriceFeeds; // token address => oracle address
    EnumerableSet.AddressSet private supportedTokens;

    uint256 public staleTolerance = 1 weeks;

    event UsdPriceFeedSet(address indexed token, address indexed feed);
    event UsdPriceFeedRemoved(address indexed token);
    event StaleToleranceSet(uint256 staleTolerance);

    constructor() {
        _initDefaultAccess(msg.sender);
        _setUsdPriceFeed(0x3EE2200Efb3400fAbB9AacF31297cBdD1d435D47, 0xa767f745331D267c7751297D982b050c93985627); // ADA
        _setUsdPriceFeed(0x8fF795a6F4D97E7887C79beA79aba5cc76444aDf, 0x43d80f616DAf0b0B42a928EeD32147dC59027D41); // BCH
        _setUsdPriceFeed(0x250632378E573c6Be1AC2f97Fcdf00515d0Aa91B, 0x2A3796273d47c4eD363b361D3AEFb7F7E2A13782); // BETH
        _setUsdPriceFeed(0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE, 0x0567F2323251f0Aab15c8dFb1967E4e8A7D42aeE); // BNB
        _setUsdPriceFeed(0x965F527D9159dCe6288a2219DB51fc6Eef120dD1, 0x08E70777b982a58D23D05E3D7714f44837c06A21); // BSW
        _setUsdPriceFeed(0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c, 0x264990fbd0A4796A3E3d8E37C4d5F87a3aCa5Ebf); // BTC (BTCB)
        _setUsdPriceFeed(0xaEC945e04baF28b135Fa7c640f624f8D90F1C3a6, 0x889158E39628C0397DC54B84F6b1cbe0AaEb7FFc); // C98
        _setUsdPriceFeed(0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82, 0xB6064eD41d4f67e353768aA239cA86f4F73665a1); // CAKE
        _setUsdPriceFeed(0x1AF3F329e8BE154074D8769D1FFa4eE058B1DBc3, 0x132d3C0B1D2cEa0BC552588063bdBb210FDeecfA); // DAI
        _setUsdPriceFeed(0xbA2aE424d960c26247Dd6c32edC70B295c744C43, 0x3AB0A0d137D4F946fBB19eecc6e92E64660231C8); // DOGE
        _setUsdPriceFeed(0x7083609fCE4d1d8Dc0C979AAb8c869Ea2C873402, 0xC333eb0086309a16aa7c8308DfD32c8BBA0a2592); // DOT
        _setUsdPriceFeed(0x2170Ed0880ac9A755fd29B2688956BD959F933F8, 0x9ef1B8c0E4F7dc8bF5719Ea496883DC6401d5b2e); // ETH
        _setUsdPriceFeed(0x0D8Ce2A99Bb6e3B7Db580eD848240e4a0F9aE153, 0xE5dbFD9003bFf9dF5feB2f4F445Ca00fb121fb83); // FIL
        _setUsdPriceFeed(0x90C97F71E18723b0Cf0dfa30ee176Ab653E89F40, 0x13A9c98b07F098c5319f4FF786eB16E22DC738e1); // FRAX
        _setUsdPriceFeed(0xAD29AbB318791D579433D831ed122aFeAf29dcfe, 0xe2A47e87C0f4134c8D06A41975F6860468b2F925); // FTM
        _setUsdPriceFeed(0xa2B726B1145A4773F68593CF171187d8EBe4d495, 0x63A9133cd7c611d6049761038C16f238FddA71d7); // INJ
        _setUsdPriceFeed(0xF8A0BF9cF54Bb92F17374d9e9A321E6a111a51bD, 0xca236E327F629f9Fc2c30A4E95775EbF0B89fac8); // LINK
        _setUsdPriceFeed(0xCC42724C6683B7E57334c4E856f4c9965ED682bD, 0x7CA57b0cA6367191c94C8914d7Df09A57655905f); // MATIC
        _setUsdPriceFeed(0xf7DE7E8A6bd59ED41a4b5fe50278b3B7f31384dF, 0x20123C6ebd45c6496102BeEA86e1a6616Ca547c6); // RDNT
        _setUsdPriceFeed(0x570A5D26f7765Ecb712C0924E4De545B89fD43dF, 0x0E8a53DD9c13589df6382F13dA6B3Ec8F919B323); // SOL
        _setUsdPriceFeed(0x40af3827F39D0EAcBF4A168f8D4ee67c121D11c9, 0xa3334A9762090E827413A7495AfeCE76F41dFc06); // TUSD
        _setUsdPriceFeed(0xBf5140A22578168FD562DCcF235E5D43A02ce9B1, 0xb57f259E7C24e56a1dA00F66b55A5640d9f9E7e4); // UNI
        _setUsdPriceFeed(0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d, 0x51597f405303C4377E36123cBc172b13269EA163); // USDC
        _setUsdPriceFeed(0x55d398326f99059fF775485246999027B3197955, 0xB97Ad0E74fa7d920791E90258A6E2085088b4320); // USDT
        _setUsdPriceFeed(0x1D2F0da169ceB9fC7B3144628dB156f3F6c60dBE, 0x93A67D414896A280bF8FFB3b389fE3686E014fda); // XRP
        _setUsdPriceFeed(0xcF6BB5389c92Bdda8a3747Ddb454cB7a64626C63, 0xBF63F430A79D4036A5900C19818aFf1fa710f206); // XVS
    }

    function setUsdPriceFeed(address token, address feed) external onlyRole(OPERATOR) {
        _setUsdPriceFeed(token, feed);
    }

    function removeUsdPriceFeed(address token) external onlyRole(OPERATOR) {
        delete usdPriceFeeds[token];
        supportedTokens.remove(token);
        emit UsdPriceFeedRemoved(token);
    }

    function setStaleTolerance(uint256 _staleTolerance) external onlyRole(OPERATOR) {
        staleTolerance = _staleTolerance;
        emit StaleToleranceSet(_staleTolerance);
    }

    function _setUsdPriceFeed(address token, address feed) private {
        require(token != address(0), "Token address cannot be zero.");
        require(feed.code.length > 0, "Price feed must be a contract.");
        usdPriceFeeds[token] = feed;
        supportedTokens.add(token);
        emit UsdPriceFeedSet(token, feed);
    }

    function getPriceInUsdUnsafe(address token) public view returns (int256, uint8, uint256) {

        address feed = usdPriceFeeds[token];
        (
            /* uint80 roundID */,
            int256 answer,
            /*uint startedAt*/,
            uint256 timeStamp,
            /*uint80 answeredInRound*/
        ) = AggregatorV3Interface(feed).latestRoundData();

        uint8 decimals = AggregatorV3Interface(feed).decimals();

        return (answer, decimals, timeStamp);
    }

    function getPriceInUsd(address token) public view override returns (int256, uint8, uint256) {
        (int256 price, uint8 decimals, uint256 timestamp) = getPriceInUsdUnsafe(token);
        require(block.timestamp - staleTolerance <= timestamp, "stale data");
        return (price, decimals, timestamp);
    }

    function getAllInfo()
    external view
    returns (string[] memory symbols, address[] memory addresses, int256[] memory prices, uint8[] memory decimals, uint256[] memory timestamps)
    {
        return _getSymbolsAddressesPricesDecimalsTimestamps(supportedTokens.values());
    }

    function getSupportedTokens()
    external view override
    returns (address[] memory) {
        return supportedTokens.values();
    }

    function isTokenSupported(address token)
    external view override
    returns (bool) {
        return supportedTokens.contains(token);
    }

    function _getSymbolsAddressesPricesDecimalsTimestamps(address[] memory tokens)
    private view
    returns (string[] memory symbols, address[] memory addresses, int256[] memory prices, uint8[] memory decimals, uint256[] memory timestamps)
    {
        uint256 len = tokens.length;
        symbols = new string[](len);
        prices = new int[](len);
        decimals = new uint8[](len);
        timestamps = new uint256[](len);
        for (uint256 i = 0; i < len; i++) {
            address feed = usdPriceFeeds[tokens[i]];
            symbols[i] = AggregatorV3Interface(feed).description();
            (prices[i], decimals[i], timestamps[i]) = getPriceInUsd(tokens[i]);
        }
        addresses = tokens;
    }
}
