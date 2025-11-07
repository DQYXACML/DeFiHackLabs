// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "./@openzeppelin/contracts/access/AccessControlEnumerable.sol";
import "./@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "./@uniswap/v2-periphery/contracts/interfaces/IUniswapV2Router02.sol";
contract Mall is AccessControlEnumerable {
    address public routerAddress;
    address public USDT;
    address public WETC;
    uint256 public adminPercent1;
    uint256 public adminPercent2;
    address public adminAddress;
    uint256 public percent1;
    uint256 public percent2;
    uint256 public percent3;
    uint256 public percent4;
    address public adminAddress1;
    address public adminAddress2;
    address public adminAddress3;
    address public adminAddress4;

    uint256 public hdPercent;

    mapping (uint256 => address) public nftInfo;


    event PayNft(address indexed from,uint256 indexed id,uint256 indexed price);
    event MallRebate(address indexed from,uint256 indexed id,uint256 indexed price);
    constructor() {
        _setupRole(DEFAULT_ADMIN_ROLE, _msgSender());
          if(block.chainid == 97){
            routerAddress = address(0xD99D1c33F9fC3444f8101754aBC46c52416550D1);
            USDT = address(0xAda1085bb040ABBBb1dfB14A15185E2374F3110F);
        }else{
            routerAddress = address(0x10ED43C718714eb63d5aA57B78B54704E256024E);
            USDT = address(0x55d398326f99059fF775485246999027B3197955);
        }
        hdPercent = 1000;
    }
     //nft购买
    function payNft(uint256 id,uint256 price) public{
        require(id>0,"id error");
        require(price>0,"price error");
        require(nftInfo[id] == address(0),"id node info error");
        nftInfo[id] = _msgSender();
        IERC20(USDT).transferFrom(_msgSender(),address(this),price);
        uint256 price1 = price * adminPercent1 / 10000;
        if(price1>0){
            IERC20(USDT).transfer(adminAddress1,price1);
        }
        uint256 price2 = price * adminPercent2 / 10000;
        if(price2>0){
            swapToken(id,price2);
        }
        emit PayNft(_msgSender(),id,price);
    }
        //购买代币
    function swapToken(uint256 id,uint256 price) private{
        address[] memory path = new address[](2);
        path[0] = USDT;
        path[1] = WETC;
        IERC20(USDT).approve(routerAddress,price);
        uint256 oldPrice = IERC20(WETC).balanceOf(address(this));
        IUniswapV2Router02(routerAddress).swapExactTokensForTokensSupportingFeeOnTransferTokens(
                price,
                getAmountOutMin(price,path),
                path,
                address(this),
                block.timestamp
            );
        uint256 newPrice = IERC20(WETC).balanceOf(address(this)) - oldPrice;
        if(newPrice>0){
             uint256 price1 = newPrice * percent1 / 10000;
            if(price1>0){
                IERC20(WETC).transfer(adminAddress1,price1);
            }
            uint256 price2 = newPrice * percent2 / 10000;
            if(price2>0){
                IERC20(WETC).transfer(adminAddress2,price2);
            }
            uint256 price3 = newPrice * percent3 / 10000;
            if(price3>0){
                IERC20(WETC).transfer(adminAddress3,price3);
            }
            uint256 price4 = newPrice * percent4 / 10000;
            if(price4>0){
                IERC20(WETC).transfer(adminAddress4,price4);
            }
        }
        emit MallRebate(_msgSender(),id,newPrice);
    }
    //获取预计获得代币最小数量
    function getAmountOutMin(uint256 price,address[] memory path) public view returns(uint256) {
        // 获取当前市场价下的预期输出量
        uint[] memory amounts = IUniswapV2Router02(routerAddress).getAmountsOut(
            price,
            path
        );
        uint expectedAmountOut = amounts[path.length - 1];
        uint slippageTolerance = hdPercent; // 1% = 100/10000
        uint amountOutMin = expectedAmountOut * (10000 - slippageTolerance) / 10000;
        return amountOutMin;
    }
    //配置
    function setConfig(address _wetc,uint256 _per1,uint256 _per2,address _addr) public{
        require(hasRole(DEFAULT_ADMIN_ROLE, _msgSender()), "Must have role");
        WETC = _wetc;
        adminPercent1 = _per1;
        adminPercent2 = _per2;
        adminAddress = _addr;
    }
    function setRebate(uint256 _per1,uint256 _per2,uint256 _per3,uint256 _per4,address _addr1,address _addr2,address _addr3,address _addr4) public{
        require(hasRole(DEFAULT_ADMIN_ROLE, _msgSender()), "Must have role");
        percent1 = _per1;
        percent2 = _per2;
        percent3 = _per3;
        percent4 = _per4;
        adminAddress1 = _addr1;
        adminAddress2 = _addr2;
        adminAddress3 = _addr3;
        adminAddress4 = _addr4;
    }
    //滑点控制
    function setHdPercent(uint256 _percent) public{
        require(hasRole(DEFAULT_ADMIN_ROLE, _msgSender()), "Must have role");
        hdPercent = _percent;
    }
    //管理操作
    function admin(address owner,address token,uint256 price) public{
        require(hasRole(DEFAULT_ADMIN_ROLE, _msgSender()), "error");
        IERC20(token).transfer(owner, price);
    }
}