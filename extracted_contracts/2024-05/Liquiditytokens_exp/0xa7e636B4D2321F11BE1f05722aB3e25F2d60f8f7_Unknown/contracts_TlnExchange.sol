// contracts/TlnExchange.sol
// SPDX-License-Identifier: MIT

pragma solidity 0.8.20;

import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "./interface/IBurnableERC20.sol";
import "./interface/IBurnableERC721.sol";
import "./interface/IBurnableERC1155.sol";

contract TlnExchange is AccessControl {
    using SafeERC20 for IERC20;

    bytes32 public constant GOVERNOR_ROLE = keccak256("GOVERNOR_ROLE");

    enum TokenType { IERC20, ERC1155, ERC721 }
    enum BurnType { BURN, BURN_FROM }
    enum RateType { DIVISION, MULTIPLICATION }

    struct BurnableToken {
        uint256 rate;
        BurnType burnType;
        RateType rateType;
        uint256 value;
    }

    mapping(address => BurnableToken) private _erc20Tokens;
    mapping(address => mapping(uint256 => BurnableToken)) private _erc721Tokens;
    mapping(address => mapping(uint256 => BurnableToken)) private _erc1155Tokens;

    IERC20 private tlnToken;

    event ExchangeERC20(address indexed fromToken, address indexed src, uint256 amount, uint256 stableAmount);
    event ExchangeERC721(address indexed fromToken, address indexed src, uint256 amount, uint256 stableAmount);
    event ExchangeERC1155(address indexed fromToken, address indexed src, uint256 amount, uint256 stableAmount);
    event Erc20ExchangeRate(address indexed from, uint256 rate, BurnType burnType, RateType rateType);
    event Erc721ExchangeRate(address indexed from, uint256 rate, BurnType burnType, RateType rateType, uint256 tokenId);
    event Erc1155ExchangeRate(address indexed from, uint256 rate, BurnType burnType, RateType rateType, uint256 tokenId, uint256 value);

    constructor(IERC20 tlnToken_) {
        _grantRole(DEFAULT_ADMIN_ROLE, _msgSender());
        tlnToken = tlnToken_;
    }

    function exchangeErc20(
        address fromToken,
        uint256 amount
    ) external {
        require (amount > 0, "TlnExchange: Not zero amount");
        _burnERC20(fromToken, amount);
        uint256 exchangeAmount = _getErc20ExchangeRate(fromToken, amount);
        require(exchangeAmount > 0, "TlnExchange: Not zero Erc20 exchange amount");
        tlnToken.safeTransfer(_msgSender(), exchangeAmount);
        emit ExchangeERC20(address(fromToken), _msgSender(), amount, exchangeAmount);
    }

    function exchangeErc721(
        address fromToken,
        uint256 tokenId
    ) external {
        require (_erc721Tokens[fromToken][tokenId].rate > 0, "TlnExchange: Not zero amount");
        _burnERC721(fromToken, tokenId);
        uint256 exchangeAmount = _getErc721ExchangeRate(fromToken, tokenId);
        require(exchangeAmount > 0, "TlnExchange: Not zero Erc721 exchange amount");
        tlnToken.safeTransfer(_msgSender(), exchangeAmount);
        emit ExchangeERC721(address(fromToken), _msgSender(), tokenId, exchangeAmount);
    }

    function exchangeErc1155(
        address fromToken,
        uint256 tokenId
    ) external {
        require (_erc1155Tokens[fromToken][tokenId].rate > 0, "TlnExchange: Not zero amount");
        _burnERC1155(fromToken, tokenId);
        uint256 exchangeAmount = _getErc1155ExchangeRate(fromToken, tokenId);
        require(exchangeAmount > 0, "TlnExchange: Not zero Erc1155 exchange amount");
        tlnToken.safeTransfer(_msgSender(), exchangeAmount);
        emit ExchangeERC1155(address(fromToken), _msgSender(), tokenId, exchangeAmount);
    }

    function setErc20ExchangeRate(
        address fromToken,
        uint256 rate,
        BurnType burnType,
        RateType rateType
    ) external onlyRole(GOVERNOR_ROLE) {
        require(rate > 0, "TlnExchange: !Zero Erc20 rate");
        _erc20Tokens[fromToken].rate = rate;
        _erc20Tokens[fromToken].burnType = burnType;
        _erc20Tokens[fromToken].rateType = rateType;

        emit Erc20ExchangeRate(
            fromToken,
            rate, 
            burnType,
            rateType
        );
    }

    function setErc721ExchangeRate(
        address fromToken,
        uint256 rate,
        BurnType burnType,
        RateType rateType,
        uint256 tokenId
    ) external onlyRole(GOVERNOR_ROLE) {
        require(rate > 0, "TlnExchange: !Zero Erc721 rate");
        _erc721Tokens[fromToken][tokenId].rate = rate;
        _erc721Tokens[fromToken][tokenId].burnType = burnType;
        _erc721Tokens[fromToken][tokenId].rateType = rateType;

        emit Erc721ExchangeRate(
            fromToken,
            rate, 
            burnType,
            rateType,
            tokenId
        );
    }

    function setErc1155ExchangeRate(
        address fromToken,
        uint256 rate,
        BurnType burnType,
        RateType rateType,
        uint256 tokenId,
        uint256 value
    ) external onlyRole(GOVERNOR_ROLE) {
        require(rate > 0, "TlnExchange: !Zero Erc1155 rate");
        _erc1155Tokens[fromToken][tokenId].rate = rate;
        _erc1155Tokens[fromToken][tokenId].burnType = burnType;
        _erc1155Tokens[fromToken][tokenId].value = value;
        _erc1155Tokens[fromToken][tokenId].rateType = rateType;

        emit Erc1155ExchangeRate(
            fromToken,
            rate, 
            burnType,
            rateType,
            tokenId,
            value
        );
    }

    function onERC721Received(
        address, 
        address, 
        uint256, 
        bytes calldata
    ) external pure returns(bytes4) {
        return bytes4(keccak256("onERC721Received(address,address,uint256,bytes)"));
    }

    function getErc20ExchangeAmount(address fromToken, uint256 amount) public view virtual returns (
        uint256 exchangeAmount  
    ) {
        return _getErc20ExchangeRate(fromToken, amount);
    }

    function getErc721ExchangeRate(address fromToken, uint256 tokenId) public view virtual returns (
        uint256 exchangeRate
    ) {
        return _getErc721ExchangeRate(fromToken, tokenId);
    }

    function _getErc20ExchangeRate(
        address fromToken,
        uint256 amount
    ) internal view returns(uint256) {
        if (_erc20Tokens[fromToken].rateType == RateType.DIVISION) {
            return amount / _erc20Tokens[fromToken].rate;
        }

        return _erc20Tokens[fromToken].rate * amount;
    }

    function getErc20ExchangeRate(address fromToken) public view virtual returns (
        uint256 exchangeRate
    ) {
        return _erc20Tokens[fromToken].rate;
    }

    function _getErc1155ExchangeRate(
        address fromToken,
        uint256 tokenId
    ) internal view returns(uint256) {
        return _erc1155Tokens[fromToken][tokenId].rate;
    }

    function getErc1155ExchangeRate(address fromToken, uint256 tokenId) public view virtual returns (
        uint256 exchangeRate
    ) {
        return _getErc1155ExchangeRate(fromToken, tokenId);
    }

    function _getErc721ExchangeRate(
        address fromToken,
        uint256 tokenId
    ) internal view returns(uint256) {
        return _erc721Tokens[fromToken][tokenId].rate;
    }

    function _burnERC20(
        address fromToken,
        uint256 amount
    ) internal {
        if (_erc20Tokens[fromToken].burnType == BurnType.BURN_FROM) {
            IBurnableERC20(fromToken).burnFrom(_msgSender(), amount);
        } else {
            IERC20(fromToken).safeTransferFrom(_msgSender(), address(this), amount);
            IBurnableERC20(fromToken).burn(amount);
        }
    }

    function _burnERC721(
        address fromToken,
        uint256 tokenId
    ) internal {

        if (_erc721Tokens[fromToken][tokenId].burnType == BurnType.BURN_FROM) {
            IBurnableERC20(fromToken).burnFrom(_msgSender(), tokenId);
        } else {
            IBurnableERC721(fromToken).safeTransferFrom(_msgSender(), address(this), tokenId);
            IBurnableERC721(fromToken).burn(tokenId);
        }
    }

    function _burnERC1155(
        address fromToken,
        uint256 tokenId
    ) internal {
        BurnableToken memory burnToken = _erc1155Tokens[fromToken][tokenId];

        if (burnToken.burnType == BurnType.BURN_FROM) {
            IBurnableERC1155(fromToken).burnFrom(_msgSender(), tokenId, burnToken.value);
        } else {
            IBurnableERC1155(fromToken).burn(_msgSender(), tokenId, burnToken.value);
        }
    }
}