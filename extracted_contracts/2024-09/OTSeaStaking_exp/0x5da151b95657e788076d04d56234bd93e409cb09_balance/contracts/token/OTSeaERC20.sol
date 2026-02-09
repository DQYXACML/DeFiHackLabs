/*
        [....     [... [......  [.. ..
      [..    [..       [..    [..    [..
    [..        [..     [..     [..         [..       [..
    [..        [..     [..       [..     [.   [..  [..  [..
    [..        [..     [..          [.. [..... [..[..   [..
      [..     [..      [..    [..    [..[.        [..   [..
        [....          [..      [.. ..    [....     [.. [...

    ERC20 Token.

    https://otsea.io
    https://t.me/OTSeaPortal
    https://twitter.com/OTSeaERC20
*/

// SPDX-License-Identifier: MIT
pragma solidity =0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@uniswap/v2-core/contracts/interfaces/IUniswapV2Factory.sol";
import "@uniswap/v2-periphery/contracts/interfaces/IUniswapV2Router02.sol";
import "contracts/helpers/TransferHelper.sol";
import "contracts/libraries/OTSeaErrors.sol";
import "contracts/libraries/OTSeaLibrary.sol";
import "contracts/token/OTSeaMigration.sol";
import "contracts/token/OTSeaRevenueDistributor.sol";
import "contracts/token/OTSeaStaking.sol";

/**
 * @title OTSea v1 ERC20 Token Overview
 * @dev This ERC20 token, part of OTSea's v1, includes specific fees for buy/sell/transfer operations:
 * - Burn Fee: A portion of tokens from each transaction is sent to the dead address.
 * - Revenue Boost Fee: A portion of tokens from each transaction is accumulated in the contract. Once over a
 *   "swap threshold", these tokens are converted to Ethereum (ETH) during sell transactions.
 *
 * All revenue fees from the token and the platform are sent to a revenue distributor contract that periodically
 * distributes fees to stakers.
 *
 * The token is managed by a multi-signature wallet, with the following capabilities:
 * - Add Initial Liquidity: Add initial liquidity into a Uniswap V2 pool.
 * - Fee Adjustment: Alter or lower the fee percentages. Note: fee increases are not permitted.
 * - Swap Threshold Management: Update the threshold for the Revenue Boost Fee conversion into ETH, within a range
 *   of 1,000 to 100,000 tokens.
 * - Transfer Fee Toggling: Can enable or disable fees on transfer. Note that this doesn't affect buy/sell fees.
 * - Transfer Fee Whitelisting: Can exempt specific addresses from paying the transfer fees. Note that this doesn't
 *   affect buy/sell fees.
 *
 * The owner, migration contract, and staking contract are permanently exempt from transfer fees. If the ownership
 * is transferred to another wallet, the new owner also becomes transfer fee exempt. The previous owner remains transfer
 * fee exempt and the new owner can decide whether or not to remove their transfer fee exempt status.
 */
contract OTSeaERC20 is Ownable, ERC20, TransferHelper {
    IUniswapV2Router02 private constant _router =
        IUniswapV2Router02(0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D);
    uint88 private constant TOTAL_SUPPLY = 100_000_000 ether;
    uint88 private constant MIN_SWAP_AT = 1_000 ether;
    uint88 private constant MAX_SWAP_AT = 100_000 ether;
    OTSeaMigration public immutable migrationContract;
    OTSeaStaking public immutable stakingContract;
    OTSeaRevenueDistributor public immutable revenueDistributor;
    bool public isTransferFeeEnabled = true;
    /// @dev Revenue boost fee is initially set to 2% of the transaction
    uint16 private _revBoostFeePercent = 200;
    /// @dev Treasury fee is initially set to 2% of the transaction
    uint16 private _treasuryFeePercent = 200;
    /// @dev Burn fee is initially set to 0% of the transaction
    uint16 private _burnFeePercent = 0;
    /// @dev Threshold at which the collected revenue boost fees are swapped to ETH and sent to the revenue distributor
    uint88 private _swapAt = 5_000 ether;
    address private _pair;
    mapping(address => bool) public isExemptFromTransferFee;

    event AddedLiquidity(address pair, uint256 token, uint256 eth);
    event FeesUpdated(uint16 revBoostFeePercent, uint16 treasuryFeePercent, uint16 burnFeePercent);
    event SwapAtUpdated(uint256 swapAt);
    event TransferFeeToggled(bool isTransferFeeEnabled);
    event TransferFeeWhitelistUpdated(address indexed account, bool whitelisted);
    event Burned(uint256 amount);
    event DistributedETHFees(uint256 revBoost, uint256 treasury);

    modifier whenFeeIsSet() {
        _checkIfFeeIsSet();
        _;
    }

    /**
     * @param _multiSigAdmin Multi-sig admin
     * @param _migrationContract Migration contract
     * @param _stakingContract Staking contract
     * @param _revenueDistributor Revenue distributor
     */
    constructor(
        address _multiSigAdmin,
        OTSeaMigration _migrationContract,
        OTSeaStaking _stakingContract,
        OTSeaRevenueDistributor _revenueDistributor
    ) ERC20("OTSea", "OTSea") Ownable(_multiSigAdmin) {
        if (
            address(_migrationContract) == address(0) ||
            address(_stakingContract) == address(0) ||
            address(_revenueDistributor) == address(0)
        ) revert OTSeaErrors.InvalidAddress();
        if (
            _migrationContract.multiSigAdmin() != _multiSigAdmin ||
            _stakingContract.owner() != _multiSigAdmin ||
            _revenueDistributor.owner() != _multiSigAdmin
        ) revert OwnableInvalidOwner(_multiSigAdmin);
        migrationContract = _migrationContract;
        stakingContract = _stakingContract;
        revenueDistributor = _revenueDistributor;
        isExemptFromTransferFee[address(_migrationContract)] = true;
        isExemptFromTransferFee[_multiSigAdmin] = true;
        isExemptFromTransferFee[address(_stakingContract)] = true;
        _mint(address(_migrationContract), TOTAL_SUPPLY);
    }

    /**
     * @notice Enter the sea
     * @param _amount Amount of OTSea to add to the initial liquidity
     */
    function enterTheSea(uint256 _amount) external payable onlyOwner {
        if (_pair != address(0)) revert OTSeaErrors.NotAvailable();
        if (_amount == 0 || msg.value == 0) revert OTSeaErrors.InvalidAmount();
        super._update(_msgSender(), address(this), _amount);
        _approve(address(this), address(_router), _amount);
        /// @dev multi-sig admin receives initial LP
        _router.addLiquidityETH{value: msg.value}(
            address(this),
            _amount,
            0,
            0,
            owner(),
            block.timestamp
        );
        address uniswapV2Pair = IUniswapV2Factory(_router.factory()).getPair(
            address(this),
            _router.WETH()
        );
        _pair = uniswapV2Pair;
        emit AddedLiquidity(_pair, _amount, msg.value);
    }

    /**
     * @notice Update the fee percents
     * @param revBoostFeePercent_ Rev boost fee percent (2 d.p. e.g. 1% = 100)
     * @param treasuryFeePercent_ Treasury fee percent (2 d.p. e.g. 1% = 100)
     * @param burnFeePercent_ Burn fee percent (2 d.p. e.g. 1% = 100)
     */
    function updateFees(
        uint16 revBoostFeePercent_,
        uint16 treasuryFeePercent_,
        uint16 burnFeePercent_
    ) external onlyOwner whenFeeIsSet {
        uint16 totalFeePercent = _getTotalFeePercent();
        uint16 newTotalFeePercent = revBoostFeePercent_ + treasuryFeePercent_ + burnFeePercent_;
        if (totalFeePercent < newTotalFeePercent) revert OTSeaErrors.InvalidFee();
        if (newTotalFeePercent == 0) {
            uint256 balance = balanceOf(address(this));
            if (balance != 0) {
                _sendToDeadAddress(address(this), balance);
            }
            delete isTransferFeeEnabled;
            delete _swapAt;
        }
        _revBoostFeePercent = revBoostFeePercent_;
        _treasuryFeePercent = treasuryFeePercent_;
        _burnFeePercent = burnFeePercent_;
        emit FeesUpdated(revBoostFeePercent_, treasuryFeePercent_, burnFeePercent_);
    }

    /**
     * @notice Update the swap at threshold at which the collected fees for rev boost and treasury get swapped for ETH
     * and distributed
     * @param _amount Amount of tokens required to trigger the swap
     */
    function updateSwapAt(uint88 _amount) external onlyOwner whenFeeIsSet {
        if (_amount < MIN_SWAP_AT || MAX_SWAP_AT < _amount) revert OTSeaErrors.InvalidAmount();
        _swapAt = _amount;
        emit SwapAtUpdated(_amount);
    }

    /// @notice Toggle transfer fee
    function toggleTransferFee() external onlyOwner whenFeeIsSet {
        isTransferFeeEnabled = !isTransferFeeEnabled;
        emit TransferFeeToggled(isTransferFeeEnabled);
    }

    /**
     * @notice Update the transfer fee whitelist
     * @param _account Account
     * @param _operation add (true) or remove (false) "account" to/from the whitelist
     */
    function updateTransferFeeWhitelist(
        address _account,
        bool _operation
    ) external onlyOwner whenFeeIsSet {
        if (_isSpecialAddress(_account)) revert OTSeaErrors.InvalidAddress();
        if (isExemptFromTransferFee[_account] == _operation) revert OTSeaErrors.Unchanged();
        _updateTransferFeeWhitelist(_account, _operation);
    }

    /**
     * @notice Get the pair address
     * @return address Pair
     */
    function getPair() external view returns (address) {
        if (_pair == address(0)) revert OTSeaErrors.NotAvailable();
        return _pair;
    }

    /**
     * @notice Get fee details
     * @return swapAt Swap at threshold where collected fees get swapped for ETH and distributed
     * @return revBoostPercent Rev boost percent
     * @return treasuryFeePercent Treasury percent
     * @return burnPercent Burn percent
     */
    function getFeeDetails()
        external
        view
        returns (
            uint256 swapAt,
            uint16 revBoostPercent,
            uint16 treasuryFeePercent,
            uint16 burnPercent
        )
    {
        return (_swapAt, _revBoostFeePercent, _treasuryFeePercent, _burnFeePercent);
    }

    /**
     * @param _from From address
     * @param _to To address
     * @param _value Value
     * @dev Overrides ERC20's _update() function in order to handle fees and disable trading prior to adding liquidity
     */
    function _update(address _from, address _to, uint256 _value) internal override {
        /**
         * @dev the following if statement works as follows:
         * - _from == address(this): makes _swapAndDistributeFees tax free
         * - _pair == address(0) && _isSpecialAddress(_from): is for when the liquidity hasn't been added yet, only
         *   special addresses are allowed to transfer
         */
        if (_from == address(this) || (_pair == address(0) && _isSpecialAddress(_from))) {
            super._update(_from, _to, _value);
            return;
        }
        if (_pair == address(0)) {
            revert OTSeaErrors.Unauthorized();
        }
        uint256 totalFee = _getTotalFeePercent();
        if (totalFee != 0) {
            if (_to == _pair && _swapAt <= balanceOf(address(this))) {
                /// @dev For sell transactions once over the threshold the contract will swap tokens for ETH
                _swapAndDistributeFees();
            }
            if (_shouldChargeFee(_from, _to)) {
                /// @dev more gas efficient passing in the totalFee than fetching it again in _takeFee()
                _value = _takeFee(totalFee, _from, _value);
            }
        }
        /// @dev buy, sell and transfers
        super._update(_from, _to, _value);
    }

    /// @param _newOwner New owner
    function _transferOwnership(address _newOwner) internal override {
        /**
         * @dev Cannot check _isSpecialAddress(_newOwner) because _transferOwnership() is called in the constructor
         * of this contract and _isSpecialAddress() contains immutable variables. Therefore we just simply only set the
         * new owner to be transfer fee exempt if it is not the zero address which is relevant if renounceOwnership()
         * is called.
         */
        if (_newOwner != address(0)) {
            _updateTransferFeeWhitelist(_newOwner, true);
        }
        super._transferOwnership(_newOwner);
    }

    /**
     * @param _totalFee Total fee
     * @param _from From address
     * @param _value Value
     * @return uint256 Value after fees
     */
    function _takeFee(uint256 _totalFee, address _from, uint256 _value) private returns (uint256) {
        /// @dev calculate fee
        uint256 fee = (_value * _totalFee) / OTSeaLibrary.PERCENT_DENOMINATOR;
        uint256 burnFee = (fee * _burnFeePercent) / _totalFee;
        if (burnFee != 0) {
            /// @dev tokens are burned immediately
            _sendToDeadAddress(_from, burnFee);
        }
        /// @dev ethFee is for the rev share boost and treasury fees (if configured)
        uint256 ethFee = fee - burnFee;
        if (ethFee != 0) {
            /// @dev tokens are stored in the contract to be later swapped for ETH
            super._update(_from, address(this), ethFee);
        }
        return _value - fee;
    }

    function _swapAndDistributeFees() private {
        /// @dev slightly cheaper in gas setting _treasuryFeePercent to a local variable
        uint256 treasuryFeePercent = _treasuryFeePercent;
        uint256 total = treasuryFeePercent + _revBoostFeePercent;
        /// @dev swaps tokens for ETH and transfers to the revenueDistributor
        uint256 eth = _swapTokensForETH();
        uint256 treasury = (eth * treasuryFeePercent) / total;
        uint256 revBoost = eth - treasury;
        if (revBoost != 0) {
            _safeETHTransfer(address(revenueDistributor), revBoost);
        }
        if (treasury != 0) {
            _safeETHTransfer(owner(), treasury);
        }
        emit DistributedETHFees(revBoost, treasury);
    }

    /// @return uint256 ETH received
    function _swapTokensForETH() private returns (uint256) {
        address[] memory path = new address[](2);
        path[0] = address(this);
        path[1] = _router.WETH();
        /// @dev sell the _swapAt amount rather than the total balance
        uint256 amount = uint256(_swapAt);
        _approve(address(this), address(_router), amount);
        uint256 ethBalanceBefore = address(this).balance;
        _router.swapExactTokensForETH(amount, 0, path, address(this), block.timestamp);
        return address(this).balance - ethBalanceBefore;
    }

    /**
     * @param _from From address
     * @param _amount Amount of tokens to send to the dead address
     */
    function _sendToDeadAddress(address _from, uint256 _amount) private {
        super._update(_from, OTSeaLibrary.DEAD_ADDRESS, _amount);
        emit Burned(_amount);
    }

    /**
     * @param _account Account
     * @param _operation add (true) or remove (false) "account" to/from the whitelist
     */
    function _updateTransferFeeWhitelist(address _account, bool _operation) private {
        isExemptFromTransferFee[_account] = _operation;
        emit TransferFeeWhitelistUpdated(_account, _operation);
    }

    /**
     * @param _account Account
     * @return bool true if _account is a special address, false if not
     */
    function _isSpecialAddress(address _account) private view returns (bool) {
        return
            _account == address(migrationContract) ||
            _account == owner() ||
            _account == address(stakingContract) ||
            _account == address(0);
    }

    /**
     * @param _from From address
     * @param _to To address
     * @return bool true if a fee should be charged, false if not
     * @dev Checks whether a fee should be charged. The logic works as follows:
     * - Buy fees are always charged unless the buyer is the staking contract
     * - Sell fees are always charged
     * - Transfer fees are charged if the transfer fee is enabled and neither the _from nor _to address are transfer
     *   fee exempt
     */
    function _shouldChargeFee(address _from, address _to) private view returns (bool) {
        return
            (_from == _pair && _to != address(stakingContract)) ||
            _to == _pair ||
            (isTransferFeeEnabled &&
                !isExemptFromTransferFee[_from] &&
                !isExemptFromTransferFee[_to]);
    }

    function _checkIfFeeIsSet() private view {
        if (_getTotalFeePercent() == 0) revert OTSeaErrors.NotAvailable();
    }

    /// @return uint16 Total fee percent
    function _getTotalFeePercent() private view returns (uint16) {
        return _revBoostFeePercent + _treasuryFeePercent + _burnFeePercent;
    }

    receive() external payable {}
}
