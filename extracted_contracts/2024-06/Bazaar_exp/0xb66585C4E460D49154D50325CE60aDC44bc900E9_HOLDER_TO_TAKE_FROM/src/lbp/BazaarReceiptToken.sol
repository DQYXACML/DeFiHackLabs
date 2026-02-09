pragma solidity ^0.7.0;
pragma experimental ABIEncoderV2;

import {IERC20} from "openzeppelin-0.7/token/ERC20/IERC20.sol";
import {ERC20} from "openzeppelin-0.7/token/ERC20/ERC20.sol";
import {SafeERC20} from "openzeppelin-0.7/token/ERC20/SafeERC20.sol";
import {Ownable} from "openzeppelin-0.7/access/Ownable.sol";

/// @dev Receipt token for LBP project token.
/// @dev The idea is to prevent LBP participants from creating liquidity pools using bought tokens.
/// @dev Instead they need to wait until the claim starts and get actual project tokens by
/// @dev burning the receipt tokens.
contract BazaarReceiptToken is ERC20, Ownable {
    using SafeERC20 for IERC20;

    /// @dev the underlying token (that carries real value) receipt token can be redeemed for
    IERC20 public immutable token;
    uint8 private _decimals;

    /// @dev if `transferRestricted` is true, the receipt token can only be transferred between user and the vault
    address public vault;
    address public factory;
    bool public transferRestricted = true;

    /// @dev whether the claim is enabled by the receipt token owner
    bool public claimEnabled = false;

    /// @dev _owner is responsible for seeding the LBP pool using the minted receipt tokens
    /// @dev _token see `token`
    constructor(address owner, address _token, address _vault, address _factory) Ownable() ERC20(_getName(_token), _getSymbol(_token)) {
        require(_token != address(0), "Token address cannot be the zero address");

        vault = _vault;
        factory = _factory;
        token = IERC20(_token);
        _decimals = _getDecimals(_token);

        if (owner != msg.sender) {
            transferOwnership(owner);
        }
    }

    function decimals() public view override returns (uint8) {
        return _decimals;
    }

    /// @dev this ensures that 1 receipt token is always backed by 1 underlying token
    function mint(uint256 amount) external onlyOwner {
        address _owner = owner();
        token.safeTransferFrom(_owner, address(this), amount);
        _mint(_owner, amount);
    }

    /// @dev override oz ERC20 _transfer so that if transferRestricted is true, the receipt token
    /// @dev can only be transferred between owner, user, and Balancer Vault
    /// @dev this is our best effort mitigation to make sure most receipt token just stays in user wallets
    function _transfer(address from, address to, uint256 value) internal virtual override {
        require(!transferRestricted || (whitelisted(from) || whitelisted(to)), "Transfer restricted");
        super._transfer(from, to, value);
    }

    /// @dev enable the claim for the receipt token
    function enableClaiming() external onlyOwner {
        require(!claimEnabled, "Claiming already enabled");
        claimEnabled = true;
    }

    function setTransferRestricted(bool _transferRestricted) external onlyOwner {
        transferRestricted = _transferRestricted;
    }

    /// @dev exchange rTOKEN for TOKEN at a 1:1 ratio
    /// @dev rTOKEN will be burned
    function claim(uint256 amount) external {
        require(claimEnabled, "Claiming not enabled");
        _burn(msg.sender, amount);
        token.safeTransfer(msg.sender, amount);
    }

    /// @dev emergency admin function to withdraw all unclaimed tokens
    function withdrawUnclaimed() external onlyOwner {
        token.transfer(owner(), token.balanceOf(address(this)));
    }

    /// @dev allowed transfers while transfers are restricted
    function whitelisted(address _address) private view returns (bool) {
        return _address == vault // allow buy/sell to lbp pool
            || _address == owner() // allow mint to owner and later on transfer to lbp pool
            || _address == factory // allow factory to disperse receipt tokens
            || _address == address(0); // allow mint and burn
    }

    /**
     * Internal Helpers *
     */
    function _getName(address underlying) internal view returns (string memory) {
        return string(abi.encodePacked("Bazaar Receipt ", ERC20(underlying).name()));
    }

    function _getSymbol(address underlying) internal view returns (string memory) {
        return string(abi.encodePacked("r", ERC20(underlying).symbol()));
    }

    function _getDecimals(address underlying) internal view returns (uint8) {
        return ERC20(underlying).decimals();
    }
}
