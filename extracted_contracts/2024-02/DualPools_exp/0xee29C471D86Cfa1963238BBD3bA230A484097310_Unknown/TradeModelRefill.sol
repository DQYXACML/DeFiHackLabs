// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.5.16;
//pragma experimental ABIEncoderV2;
import "./SafeMath.sol";
import "./SignedSafeMath.sol";
import "./VTokenInterfaces.sol";

/**
 * 1) Teir 1 (USDT, USDC): 0.10% trade fee + slippage 0.001%
 *    Teir 2 (BTC, ETH, BNB): 0.10% trade fee + slippage 0.01% at 50k (BNB 0.03%)
 *    Teir 3 (SOL, XRP): 0.10% trade fee + slippage 0.03% at 50k
 *    Teir 4 (ADA, AVAX, DOGE, LINK): 0.10% trade fee +  slippage 0.08% at 50k
 *
 * Teir Discount:
 *    Tier 1 and any other: 50% off
 *    Teir 2 and Teir 2: 50% off
 *    Everything else: no discount
 *
 * Teir Discount: 50% off trade fees if paired with at least one teir 1 (BTC/USDT)
 *
 * Trader Discounts: up to 10% XDP discount, 5% referral reward
 * Reserves: 5% of total fee amount
 * Min Trader Fee In = 0.05% * (1.0 - 0.10-0.05) = 0.0425% (0.0404% to pool, 0.0021% to reserves)
 * Min Trader Fee Out = 0.05% * (1.0 - 0.10) = 0.045% (0.04275% to pool, 0.00225% to reserves)
 * Total Trade Fee = 0.085% (0.08315% to pool, 0.00435% to reserves)
 *
 * Refiller Reward: up 80% of the fee as reward, advantagous slippage
 * Max Refiller: 0.10% * 80% = 0.80% + pre-slippage reward 
 *
 */



contract TradeModel is ITradeModel {

    using SafeMath for uint;
    using SignedSafeMath for int;

    // ---------- PUBLIC VARIABLES ------------- // 

    /**
     * @notice dToken for BNB
     */
    address public dBNB;

    /**
     * @notice Allows to change some values within a hardcoded limit
     */
    address public admin;

    /**
     * @notice Percentage of trade amount that is charged for fee
     * @dev Applied twice from tokenA --> tokenB. Once from tokenA --> USD and again from USD --> tokenB
     * teir 0: 0.0006e18
     * teir 1-5: 0.0010e18
     */
    uint public tradeFeePerc = 0.0006e18; 

    /**
     * @notice High volume coins with vast direct trading pairs a teir 1, others teir 2
     * @dev Fees are adjusted according to trading pair teir combinations
     * teir 0: speical case due to limited input | BNB -->  always 0.06% fee and 0.0005e18 slippage (0.025% to 0.125% for others based on teir)
     * teir 1: excelent trading pairs on Binance | USDT, USDC --> 0.00001e18 slippage
     * teir 2: good trading pairs on Pancakeswap | BTCB, ETH --> 0.0001e18 slippage
     * teir 3: terrible on PCS, okay on Binance | SOL, XRP, ADA, AVAX, DOGE, LINK --> 0.0010e18 slippage 
     */
    uint8 public teir = 0; 


    /**
     * @notice Percentage of trading fees that goes to reserves
     */
    uint public tradeReserveFactor = 0.04e18; 

    /**
     * @notice Referral gets 40% off trading fees
     */
    uint public constant referralDiscount = 0e18; 

    /**
     * @notice Maximum amount (in percent) the asset can move from oracle
     * @dev i.e max slippage
     */
    uint public priceImpactLimit = 0.05e18;

    /**
     * @notice Sets the slippage price impact curve based on iUSD rate
     * @dev Straight line started at (0,0) to (100%, slippageSlope)
     * $default: stables: 0.00001e18, largeCap: 0.0001e18, midCap: 0.0003e18, lowCap: 0.0008e18
     * teir 0 (BNB):       0.0005e18
     * teir 1 (USDT,USDC): 0.00001e18
     * teir 2 (BTCB,ETH):  0.0001e18
     * teir 3 (alts):      0.0010e18
     */
    uint public slippageSlope =0.0005e18;  


    /**
     * @notice The percent discounts on trading fees
     */
    uint public shrimpDiscount = 0.05e18; // pay 95% of tradeFeePerc
    uint public fishDiscount   = 0.08e18; // pay 92% of tradeFeePerc
    uint public sharkDiscount  = 0.10e18; // pay 88% of tradeFeePerc


    /**
     * @notice The thresholds for associated trading fee discounts
     */
    uint public shrimpThreshold = 1000e18; // 1,000 XRP (0.00333% supply)
    uint public fishThreshold   = 10000e18; // 10,000 XDP (0.0333% supply)
    uint public sharkThreshold  = 100000e18; // 100,000 XDP (0.333% supply)

    /**
     * @notice Sets the amount of XDP needed to get refillerReward
     * @dev The refiller reward cannot exceed the pool earnings (minus reserves) from highest discounted trade
     */
    uint public refillerReward  = 0.775e18; // earn 80% of tradeFeePerc  
    uint public refillerThreshold  = 1000000e18; // 1,000,000 XDP (3.33% supply) 


    // ---------- CONSTRUCTOR AND MODIFIER ------------- //

    /**
     * mainnet: 0xB5aAaCcFd69EA45b1A5Aa7E9c7a5e0DB2ce4357e
     * testnet: 0xe3F7e1B2C75103bc1a3AcA6050d0C9084Ba077aF
     */
    constructor(address _dBNB) public {
        admin = msg.sender;
        dBNB = _dBNB;
    }


    /**
     * @notice Restricts functions to admin
     */
    modifier onlyAdmin() {
        require(msg.sender == admin, "!admin");
        _;
    }


    // ---------- ADMIN FUNCTIONS ------------- //

    event DBNB(address oldDBNB, address newDBNB);
    /**
     * @notice Allows admin to change dBNB address
     * @dev Cannot be zero address
     * @param _dBNB New dBNB address
     */
    function _setDBNB(address _dBNB) external onlyAdmin() {
        require(_dBNB != address(0),"!dBNB cannot be zero address");
        address oldDBNB = dBNB;
        dBNB = _dBNB;
        emit DBNB(oldDBNB, dBNB);
    }

    event SetTradeFee(uint oldTradeFee, uint newTradeFee);
    /**
     * @notice Allows admin to set trading fee (before discounts)
     * @dev Must be below 2%
     * @param _tradeFeePerc New trading fee
     */
    function _setTradeFee(uint _tradeFeePerc) external onlyAdmin() {
        require(_tradeFeePerc<=0.02e18,"!tradeFee");
        uint oldTradeFee = tradeFeePerc;
        tradeFeePerc = _tradeFeePerc;
        emit SetTradeFee(oldTradeFee, tradeFeePerc);
    }


    event SetTeir(uint oldTeir, uint newTeir);
    /**
     * @notice Allows admin to set trading fee (before discounts)
     * @dev Must be below 2%
     * @param _teir New trading fee
     */
    function _setTeir(uint8 _teir) external onlyAdmin() {
        require(_teir<=3,"!_teir");
        uint oldTeir = teir;
        teir = _teir;
        emit SetTeir(oldTeir, teir);
    }


    event SetTradeReserveFactor(uint oldReserveFactor, uint newReserveFactor);
    /**
     * @notice Allows admin to set percentage of trade fee that goes to reserves
     * @dev Must be below 100% (of trading fee)
     * @param _tradeReserveFactor New reserve factor
     */
    function _setTradeReserveFactor(uint _tradeReserveFactor) external onlyAdmin() {
        require(_tradeReserveFactor <= 1e18,"!tradeReserveFactor");
        uint oldReserveFactor = tradeReserveFactor;
        tradeReserveFactor = _tradeReserveFactor;
        emit SetTradeReserveFactor(oldReserveFactor, tradeReserveFactor);

    }

    event oldTradeFeeThresholds(uint shrimpThres, uint fishThres, uint sharkThres, uint refillerThres);
    event newTradeFeeThresholds(uint shrimpThres, uint fishThres, uint sharkThres, uint refillerThres);
    /**
     * @notice Allows admin to change trading fee discount thresholds (i.e how much XDP must be held to receive discount)
     * @dev shrimpThres < fishThres < sharkThres, whaleThres
     */
    function _updateTradeFeeDiscountThresholds(uint _shrimpThres, uint _fishThres, uint _sharkThres, uint _refillerThres) external onlyAdmin() {
        require(_shrimpThres <  _fishThres && _fishThres < _sharkThres && _sharkThres < _refillerThres,"!threshold");
        emit oldTradeFeeThresholds(shrimpThreshold, fishThreshold, sharkThreshold, refillerThreshold);
        shrimpThreshold = _shrimpThres;
        fishThreshold = _fishThres;
        sharkThreshold = _sharkThres;
        refillerThreshold = _refillerThres;
        emit newTradeFeeThresholds(shrimpThreshold, fishThreshold, sharkThreshold, refillerThreshold);
    }


    event oldTradeFeePercents(uint shrimpDisc, uint fishDisc, uint sharkDisc, uint whaleDisc);
    event newTradeFeePercents(uint shrimpDisc, uint fishDisc, uint sharkDisc, uint whaleDisc);
    /**
     * @notice Allows admin to change trading fee discount percents (i.e how much XDP must be held to receive discount)
     * @dev shrimpThres < fishThres < sharkThres, whaleThres
     */
    function _updateTradeFeeDiscountPercents(uint _shrimpDis, uint _fishDis, uint _sharkDis, uint _refillerRew) external onlyAdmin() {
        require(_shrimpDis <  _fishDis && _fishDis < _sharkDis && _sharkDis < _refillerRew && _refillerRew <= 1e18,"!threshold");
        uint maxRefillerReward = (_sharkDis.add(referralDiscount)).mul(1e18).div(uint(1e18).sub(tradeReserveFactor));
        require(_refillerRew <= maxRefillerReward,"refiller discount reward must not exceed ");
        emit oldTradeFeePercents(shrimpDiscount, fishDiscount, sharkDiscount, refillerReward);
        shrimpDiscount = _shrimpDis;
        fishDiscount = _shrimpDis;
        sharkDiscount = _sharkDis;
        refillerReward = _refillerRew;
        emit newTradeFeePercents(shrimpDiscount, fishDiscount, sharkDiscount, refillerReward);
    }

    event SetPriceImpactLimit(uint oldLimit, uint newLimit);
    /**
     * @notice Allows admin to change the price impact limit
     * @dev limit must be below 100% (1e18)
     */
    function setPriceImpactLimit(uint _limit) external onlyAdmin() {
        require(_limit <= 1e18, "invalid price impact limit");
        uint oldLimit = priceImpactLimit;
        priceImpactLimit = _limit;
        emit SetPriceImpactLimit(oldLimit, priceImpactLimit);
    }


    event SetSlippageSlope(uint oldSlippage, uint newSlippage);
    /**
     * @notice Allows admin to change the slope of the price impact curve
     * @dev Slippage slope can be above 100% as price Impact Limit will limit it
     *      this will just help it reach the price impact limit quicker
     */
    function setSlippageSlope(uint _slippageSlope) external onlyAdmin() {
        require(_slippageSlope <= 100e18, "invalid slippage slope");
        uint oldSlippage = slippageSlope;
        slippageSlope = _slippageSlope;
        emit SetSlippageSlope(oldSlippage, slippageSlope);
    }



    // ---------------------------   HELPER FUNCTIONS   ----------------------------------- //


    function getValue(uint256 _amount, uint256 _price) public pure returns(uint256) {
        //return _amount * _price / 1e18;
        return _amount.mul(_price).div(1e18);
    }

    function getAssetAmt(uint256 _amount, uint256 _price) public pure returns(uint256) {
        //return _amount * 1e18 / _price;
        return _amount.mul(1e18).div(_price);
    }

    function getValueInt(int _amount, int _price) public pure returns(int) {
        return _amount.mul(_price).div(1e18);
    }


    function getAssetAmtInt(int _amount, int _price) public pure returns(int) {
        return _amount.mul(1e18).div(_price);
    }

    function abs(int256 x) public pure returns (uint256) {
        return x >= 0 ? uint256(x) : uint256(-x);
    }

    // ------------------------- EXTERNAL FUNCTIONS --------------------- // 

    // ----- Lens/External Functions ----- // 

    /**
     * @notice Returns the iUSD rate for use by the Lens
     */
    function iUSDrate(int _iUSDbalance, uint _availCash, uint _price) external pure returns(int rate) {
        rate = iUSDrateInternal(_iUSDbalance, _availCash, _price);
    }


    /**
     * @notice Returns the price impact percent for use by the Lens
     */
    function priceImpactExt(int _iUSDbalance, uint _availCash, uint _price) external view returns(int rate) {
        rate = priceImpact(_iUSDbalance, _availCash, _price);
    }


    /**
     * @notice Returns the adjust price for use by the Lens
     */
    function adjustedPriceExt(int _iUSDbalance, uint _availCash, uint _price) external view returns(uint adjPrice) {
        adjPrice = adjustedPrice(_iUSDbalance, _availCash, _price);

    }


    // ---------------------------   IUSD AND PRICE   ----------------------------------- //


    /**
     * @notice Calculates the current iUSD rate of the market: 
     * @dev formula: `iUSD balance / (availCash*price + _iUSDbalance)`
     * @param _iUSDbalance The iUSD balance of dToken
     * @param _availCash The available cash (getCashPrior()) of dToken
     * @param _price The oracle price of the underling asset
     * @return rate The iUSD rate of the dToken 
     */
    function iUSDrateInternal(int _iUSDbalance, uint _availCash, uint _price) public pure returns(int rate) {
        // need to add in case where  pool balance is 0! 
        uint poolValue = getValue(_availCash, _price);
        int poolValuePlusIUSD = int(poolValue).add(_iUSDbalance);
        if (poolValuePlusIUSD <= 0) {
            rate = -1e18;
        } else {
            rate = getAssetAmtInt(_iUSDbalance,poolValuePlusIUSD);
            if (rate > 1e18) {
                rate = 1e18;
            } else if (rate < -1e18) {
                rate = -1e18;
            }
        }
    }


    /**
     * @notice Calculates the current price impact of the market
     * @dev formula: 'iUSDrate() * abs(iUSDrate())'
     * @param _iUSDbalance The iUSD balance of dToken
     * @param _availCash The available cash (getCashPrior()) of dToken
     * @param _price The oracle price of the underling asset
     * @return rate The price impact (in percent) of the dToken
     */
    function priceImpact(int _iUSDbalance, uint _availCash, uint _price) public view returns(int rate) {
        int _iUSDrate = iUSDrateInternal(_iUSDbalance, _availCash, _price);
        rate = getValueInt(int(slippageSlope),_iUSDrate); // 10% * 10% --> 1%
        
        // Ensure price impact is not an unexpected high value
        int _priceImpactLimit = int(priceImpactLimit);
        if (rate > _priceImpactLimit) {
            rate = _priceImpactLimit;
        } else if (rate < -_priceImpactLimit) {
            rate = -_priceImpactLimit;
        }
    }


    /**
     * @notice Applies price impact to oracle price
     * @param _iUSDbalance The current iUSDbalance of the dToken
     * @param _iUSDbalance The current cashPrior() of the dToken
     * @param _price The current oracle price of asset being remove
     * @return adjPrice Returns the adjusted price (trading price)
    */
    function adjustedPrice(int _iUSDbalance, uint _availCash, uint _price) internal view returns(uint adjPrice) {
        int _priceImpact = priceImpact(_iUSDbalance, _availCash, _price);
        int oneMinusAbsPriceImpact = int(1e18).sub(int(abs(_priceImpact)));
        if (oneMinusAbsPriceImpact>0) { // premium
            if (_priceImpact <=0) {
                adjPrice = getValue(_price, uint(oneMinusAbsPriceImpact));
            } else {
                adjPrice = getAssetAmt(_price,uint(oneMinusAbsPriceImpact));
            }
        } else { // discount
            revert("price impact must be smaller than 100%");
        }
    }


    /**
     * @notice Calculates the protocol loss if a trader would buy (sell) an asset in an infinite number of 
     *         trades at discounted (premium) prices until the iUSDrate() goes to 0
     * @dev Formula uses the integral of the price impact function: 0.0002x --> x^2/10,000
     * @param _iUSDbalance The iUSD balance of dToken
     * @param _availCash The available cash (getCashPrior()) of dToken
     * @param _price The oracle price of the underling asset
     * @return rate The protocol loss (in USD) of dToken in current state
     */
    function protocolLoss(int _iUSDbalance, uint _availCash, uint _price) public view returns(uint loss) {
        int _iUSDrate = iUSDrateInternal(_iUSDbalance, _availCash, _price);
        uint iUSDrateSquared = uint(_iUSDrate.mul(_iUSDrate).div(1e18));
        uint integralFactor = slippageSlope.mul(1e18).div(2e18);
        uint priceImpactIntegral = iUSDrateSquared.mul(integralFactor).div(1e18);
        loss = priceImpactIntegral; // in USD
    }


    /**
     * @notice Calculates the fee when removing liquidity (borrow or redeem) from dToken
     * @dev This calculation is used when redeeming/borrowing assets to prevent an exploit where the trader removes 
     *      liquidity from the protocol, increasing |iUSDrate|, then taking advantage of price premium or discount
     * @param removeLiquidity Amount user wishes to remove from dToken (in Underlying amount)
     * @param _iUSDbalance The current iUSDbalance of the dToken
     * @param _iUSDbalance The current cashPrior() of the dToken
     * @param _price The current oracle price of asset being remove
     */
    function removeLiquidityFee(uint removeLiquidity, int _iUSDbalance, uint _availCash, uint _price) public view returns(uint fee) {
        uint startProtocolLoss = protocolLoss(_iUSDbalance, _availCash, _price);
        uint newAvailableCash = _availCash.sub(removeLiquidity);
        uint endProtocolLoss = protocolLoss(_iUSDbalance, newAvailableCash, _price);

        require(endProtocolLoss >= startProtocolLoss,"remove liquidity would result in less protocol loss. Something wrong");

        uint feeUSD = endProtocolLoss.sub(startProtocolLoss);
        fee =  getAssetAmt(feeUSD,_price);
    }


    /**
     * @notice Calculates the fee when removing liquidity (borrow or redeem) from dToken
     * @dev This calculation is used when redeeming/borrowing assets to prevent an exploit where the trader removes 
     *      liquidity from the protocol, increasing |iUSDrate|, then taking advantage of price premium or discount
     * @param removeLiquidity Amount user wishes to remove from dToken (in Underlying amount)
     * @param _iUSDbalance The current iUSDbalance of the dToken
     * @param _iUSDbalance The current cashPrior() of the dToken
     * @param _price The current oracle price of asset being remove
     */
    function newRemoveLiquidityAmt(uint removeLiquidity, int _iUSDbalance, uint _availCash, uint _price) public view returns(uint newAmt) {
        uint _removeLiquidityFee = removeLiquidityFee(removeLiquidity, _iUSDbalance,  _availCash, _price);
        int _newAmt = int(removeLiquidity).sub(int(_removeLiquidityFee));
        require(_newAmt>=0,"!newAmt");
        newAmt = uint(_newAmt);
    }



    // ---------------------------   CASH MODIFICATION  ----------------------------------- //


    /**
     * @notice Calculates the true value of the protocol
     * @dev Used for the exchangeRate calculation
     * @param iUSDbalance The current iUSDbalance of the dToken
     * @param availCash The current cashPrior() of the dToken
     * @param oraclePrice The current oracle price of asset being remove
     * @return cashPlusUSD Returns the true value of in protocol 
     */
    function cashAddUSDMinusLoss(int iUSDbalance, uint availCash, uint oraclePrice) public view returns(uint cashPlusUSD) {
        uint _protocolLoss = protocolLoss(iUSDbalance, availCash, oraclePrice);
        int iUSDbalanceMinusLoss = iUSDbalance.sub(int(_protocolLoss));
        int _cashAddUSD = int(availCash).add(getAssetAmtInt(iUSDbalanceMinusLoss,int(oraclePrice)));
        if (_cashAddUSD>0) {
            cashPlusUSD = uint(_cashAddUSD);
        } else {
            cashPlusUSD = 0;
        }
    }


    /**
     * @notice Calculates the available cash in the pool 
     * @dev Used to determine how much can be borrowed/redeemed
     * @param iUSDbalance The current iUSDbalance of the dToken
     * @param availCash The current cashPrior() of the dToken
     * @param oraclePrice The current oracle price of asset being remove
     * @return cashAddUSDMultUSDrate Returns the available cash in pool 
     */
    function getCashAddUSDMultAbsRate(int iUSDbalance, uint availCash, uint oraclePrice) external view returns(uint cashAddUSDMultUSDrate) {
        int cashPlusUSD =  int(availCash).add(getAssetAmtInt(iUSDbalance,int(oraclePrice)));
        if (cashPlusUSD > 0) {
            uint OneMinusAbsUSDrate = uint(1e18).sub(abs(iUSDrateInternal(iUSDbalance, availCash, oraclePrice)));
            cashAddUSDMultUSDrate = getValue(uint(cashPlusUSD), OneMinusAbsUSDrate);
        } else {
            cashAddUSDMultUSDrate = 0;
        }
    } 


    // ---------------------------   FEE AND AMOUNT OUT   ----------------------------------- //


    /**
     * @notice Returns the discount applied to traders 
     * @param _traderBalance The balance of XDP the trader has
     * @return discount The percent discount the trader receives on trading fees
     */
    function feeDiscount(uint _traderBalance) public view returns(uint discount) {
        if (_traderBalance >= sharkThreshold) {
            discount = sharkDiscount;
        } else if (_traderBalance >= fishThreshold) {
            discount = fishDiscount;
        } else if (_traderBalance >= shrimpThreshold) {
            discount = shrimpDiscount;
        } else {
            discount = 0;
        }
    }


    /**
     * @notice Calculates the discount on this dTokens fee based on combination with other dToken teir
     */
    function teirDiscountOrFee(uint _teirOther) public view returns(uint) {

        uint tradeFeePercent = tradeFeePerc; // 0.10% (before discounts)
        
        if (teir == uint8(0)) {
            tradeFeePercent = tradeFeePerc; // always fixed
        }else if (_teirOther == uint8(0)) { // dBNB will have static fee of 0.075% 
            if (teir == uint8(1) || teir == uint8(2)) {
                tradeFeePercent = tradeFeePerc.mul(0.25e18).div(1e18); // (0.075% + this 0.025%)
            } else { // otherTeir is 1, 2, or 3 (50% off)
                tradeFeePercent = tradeFeePerc.mul(1.25e18).div(1e18); // (0.075% + this 0.125%)
            }
        } else if (_teirOther == uint8(1) || teir == uint8(1)) {
            tradeFeePercent = tradeFeePerc.mul(0.5e18).div(1e18);
        } else if (_teirOther == uint8(2)) {
            if (teir == uint8(1) || teir == uint8(2)) {
                tradeFeePercent = tradeFeePerc.mul(0.50e18).div(1e18); // (0.05% + this 0.05%)
            } 
        }
        return tradeFeePercent;
    }


    /**
     * @notice Calculates amountIn after Teir Discount, Referral Discount, and XDP Discount 
     * @dev Fee is charged to traders/arbitragers, fee is earned for refillers 
     */
    function amountsInAfterDiscountsOrReward(address dTokenOther, uint amountIn,uint _traderBalXDP, address referrer, bool refiller) public view returns(uint amountOut) {

        // generates trade fee based on teir combination
        uint8 teirOther = VTokenInterface(dTokenOther).tradeModel().teir();
        uint tradeFeePercent = teirDiscountOrFee(teirOther);

        if (refiller) { // applies refiller rewards if trader meets conditions
            
            uint _refillerReward = tradeFeePercent.mul(refillerReward).div(1e18);
            amountOut = amountIn.mul(uint(1e18).add(_refillerReward)).div(1e18);

        } else { // Apply potential referral and XDP discounts to trader
            
            uint _referralDiscount;
            if (referrer != address(0)) {_referralDiscount = referralDiscount;}
            uint discountXDP = feeDiscount(_traderBalXDP);
            uint oneMinusDiscounts = uint(1e18).sub(discountXDP).sub(_referralDiscount);
            tradeFeePercent = getValue(tradeFeePercent , oneMinusDiscounts);
            amountOut = amountIn.mul(uint(1e18).sub(tradeFeePercent)).div(1e18);

        }
        
    }


    /**
     * @notice Calculates the amount of USD out after user sold underlying
     * @dev trading fee and trading price is applied
     * @dev refiller uses pre iUSD balance to get larger 
     * @param _amountTokenIn The amount of underlying token user is selling
     * @param _initialPrice The oracle price of the asset being sold 
     * @param _iUSDbalance iUSD balance of dToken associated with underlying being sold
     * @param _postCash The available cash after BNB/Bep20 is deposited into contract
     * @param _traderBalXDP The XDP balance held in traders wallet 
     * @return amtOutUSD USD value out, reserveFeeUnderly Amount that goes to reserves, totalFeeAmt Total fees (in Underlying)
     */
    function amountOutUSDInternal(address _dTokenOther, uint _amountTokenIn, uint _initialPrice, int _iUSDbalance, uint _postCash, uint _traderBalXDP, address _referrer) public view returns(uint amtOutUSD, uint reserveFeeUnderly, uint totalFeeAmt) {

        uint pricePost = _initialPrice;
        uint amountTokenInAfterFeeOrReward = _amountTokenIn;
        int iUSDpostEst = _iUSDbalance.sub(int(getValue(_amountTokenIn, _initialPrice)));
        if (_traderBalXDP > refillerThreshold && iUSDpostEst > 0) {

            // get refiller values (apply fee as a reward)
            amountTokenInAfterFeeOrReward = amountsInAfterDiscountsOrReward(_dTokenOther,_amountTokenIn, _traderBalXDP, _referrer,true); // add reward

            // gets exact price using current iUSDbalance due to refiller trade
            pricePost = adjustedPrice(_iUSDbalance, _postCash, _initialPrice);
            amtOutUSD = getValue(amountTokenInAfterFeeOrReward,pricePost);
            totalFeeAmt = amountTokenInAfterFeeOrReward.sub(_amountTokenIn); // actually a reward
            reserveFeeUnderly = 0;
        
        } else {

            // get trader values (apply fee)
            amountTokenInAfterFeeOrReward = amountsInAfterDiscountsOrReward(_dTokenOther,_amountTokenIn, _traderBalXDP, _referrer,false); // sub fee

            // gets first post estimates using iUSDpostEst
            pricePost = adjustedPrice(iUSDpostEst, _postCash, _initialPrice);

            // get second (more accurate) post estimates
            iUSDpostEst = _iUSDbalance.sub(int(getValue(_amountTokenIn, pricePost)));
            pricePost = adjustedPrice(iUSDpostEst, _postCash, _initialPrice);

            // get third (most accurate) post estimates
            iUSDpostEst = _iUSDbalance.sub(int(getValue(_amountTokenIn, pricePost)));
            pricePost = adjustedPrice(iUSDpostEst, _postCash, _initialPrice);

            amtOutUSD = getValue(amountTokenInAfterFeeOrReward,pricePost);
            totalFeeAmt = _amountTokenIn.sub(amountTokenInAfterFeeOrReward);
            reserveFeeUnderly = getValue(totalFeeAmt,tradeReserveFactor); // some of fee goes to reserves

        }


    }


    /**
     * @notice Calculates the amount of Underling out based on USD in
     * @dev trading fee and trading price is applied
     * @param _amtInUSD The value (in USD) in
     * @param _initialPrice The oracle price of the asset being sold 
     * @param _iUSDbalance iUSD balance of dToken associated with underlying being sold
     * @param _availCash The available cash (getCashPrior()) in the dToken
     * @param _traderBalXDP The XDP balance held in traders wallet 
     * @return amountOutToken Underlying out, reserveFeeUnderly Amount that goes to reserves, totalFeeAmt Total fees (in Underlying)
     */
    function amountOutTokenInternal(address _dTokenOther, uint _amtInUSD, uint _initialPrice, int _iUSDbalance, uint _availCash, uint _traderBalXDP) public view returns(uint amountOutToken, uint reserveFeeUnderly, uint totalFeeAmt) {

        // trade fee after teir discount, xdp discount, and referral reward (all as reward if refiller)
        //uint totalTradeFeePerc = tradingFeeAfterDiscounts(_dTokenOther, _traderBalXDP, address(0));
        
        // Vary values based on refiller or trader
        uint totalFeeAmountUSD; // zero if refiller
        uint amountIUSDInAfterFeeOrReward;
        int iUSDpost = _iUSDbalance.add(int(_amtInUSD));
        if (_traderBalXDP > refillerThreshold && iUSDpost < 0) { // refiller conditions
            
            iUSDpost = _iUSDbalance; // refiller uses pre iUSD for slippage advantage
            amountIUSDInAfterFeeOrReward = amountsInAfterDiscountsOrReward(_dTokenOther,_amtInUSD, _traderBalXDP, address(0),true); // add reward

        } else {

            amountIUSDInAfterFeeOrReward = amountsInAfterDiscountsOrReward(_dTokenOther,_amtInUSD, _traderBalXDP, address(0),false); // sub fee
            totalFeeAmountUSD = _amtInUSD.sub(amountIUSDInAfterFeeOrReward);

        }
        
        // get first post estimates
        uint tokenPostEst = _availCash.sub(getAssetAmt(amountIUSDInAfterFeeOrReward, _initialPrice));
        uint pricePost = adjustedPrice(iUSDpost, tokenPostEst, _initialPrice);

        // get second (more accurate) post estimates
        tokenPostEst = _availCash.sub(getAssetAmt(amountIUSDInAfterFeeOrReward, pricePost));
        pricePost = adjustedPrice(iUSDpost, tokenPostEst, _initialPrice);

        // get third (more accurate) post estimates
        tokenPostEst = _availCash.sub(getAssetAmt(amountIUSDInAfterFeeOrReward, pricePost));
        pricePost = adjustedPrice(iUSDpost, tokenPostEst, _initialPrice);

        // get amount out
        amountOutToken = getAssetAmt(amountIUSDInAfterFeeOrReward,pricePost);
        totalFeeAmt = getAssetAmt(totalFeeAmountUSD,pricePost); // zero if refiller
        reserveFeeUnderly = getValue(totalFeeAmt,tradeReserveFactor); // zero if refiller

    }


    /**
     * @dev Unable to change dBNB in current Trend Token, so as default its zero address
     */
    function dTokenAdjustForBNB(address dToken) public view returns(address) {
        if (dToken == address(0)) {
            return dBNB;
        } else {
            return dToken;
        }
    }


    /**
     * @notice Calculates the amount of Underlying out (for dTokenOut) based on amountIn of dTokenIn's underlying
     * @dev Combines amountOutUSDInternal and amountOutTokenInternal into one function
     *      The dToken calling this function will either be buying (dTokenIn = 0x00) or selling (dTokenOut = 0x00) its underlying
     *      Need to deduct amountIn from availableCash when selling underlying because the calling function receives underlying first
     * @param _dTokenIn Address of dToken assocaited with underlying being sold
     * @param _dTokenOut Address of dToken assocaited with underlying being bought
     * @param amountIn The amount of Underlying in associated with dTokenIn
     * @param oraclePrice The oracle price of the asset being sold 
     * @param iUSDbalance iUSD balance of dToken associated with underlying being sold
     * @param availCash The available cash (getCashPrior()) in the dToken
     * @param traderBalanceXDP The XDP balance held in traders wallet 
     * @return amountOut Amount of USD or underlying out, reserveFeeUnderly Underlying that goes to reserves, totalFeeAmt Total fees (in Underlying)
     */
    function amountsOut(address _dTokenIn, address _dTokenOut, uint amountIn, uint oraclePrice, int iUSDbalance, uint availCash, uint traderBalanceXDP, address _referrer) external view returns(uint amountOut, uint reserveFeeUnderly, uint totalFeeAmt)  {
        require(_dTokenIn==msg.sender || _dTokenOut==msg.sender,"dTokenIn or dTokenOut must be msg.sender");
        // swapping underlying (selling) for valueUSD
        if ( _dTokenIn == msg.sender) { // dTokenIn == msg.sender (selling dToken --> iUSD)
            address dTokenOut = dTokenAdjustForBNB(_dTokenOut);
            (amountOut, reserveFeeUnderly,totalFeeAmt) = amountOutUSDInternal(dTokenOut,amountIn, oraclePrice, iUSDbalance, availCash, traderBalanceXDP,_referrer);

        // swapping valueUSD for underlying (buying
        } else {
            address dTokenIn = dTokenAdjustForBNB(_dTokenIn);
            (amountOut, reserveFeeUnderly,totalFeeAmt) = amountOutTokenInternal(dTokenIn, amountIn, oraclePrice, iUSDbalance, availCash, traderBalanceXDP);
        
        } 

    }


// dUSDT: 100000000000000000000,0,["0x67DAB885c014FBB42a73f15F87953EE9c619910a","0x0000000000000000000000000000000000000000"],"0x250642F2860532610f1B0CF867420a7633819b26",10000000000000000000000000
// dBTCB: 1200000000000000,0,["0xE1c0149f90E275893624c1963Cb6f9daB1383807","0x0000000000000000000000000000000000000000"],"0x250642F2860532610f1B0CF867420a7633819b26",10000000000000000000000000000
}

