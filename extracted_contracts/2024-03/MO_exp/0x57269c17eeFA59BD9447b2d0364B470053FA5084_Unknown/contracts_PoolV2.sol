// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

import "./interfaces/IUniswapV2Factory.sol";
import "./interfaces/IUniswapV2Router.sol";
import "./interfaces/IUniswapV2Pair.sol";
import "./interfaces/IRelationship.sol";
import "./interfaces/INode.sol";
import "./interfaces/IVault.sol";
import "./interfaces/IToken.sol";
import "./interfaces/IPoolV1.sol";
import "./interfaces/IApproveProxy.sol";

contract PoolV2 is Ownable {
    using SafeERC20 for IERC20;

    uint256 public constant BASE = 10000;
    address public recipient;
    address public usdt; // USDT
    address public token;
    address public relationship;
    address public node;
    address public vault;
    address public router;
    address public pair;
    uint256 public amountMin; // 100
    uint256 public amountMax; // 2000
    uint256 public rewardRate; // 1.4
    uint256 public rewardRatePreDay; // 1e6 * 7000 / 10000 * 180 / 10000
    uint256 public depthMax;

    address public poolV1;
    address public approveProxy;

    mapping(address => Order) public orders;

    struct Config {
        uint256 performance; // 业绩
        uint256 rewardRate; // 收益率
    }

    mapping(uint256 => Config) public configs;
    mapping(address => uint256) public levels;
    mapping(address => uint256) public performances;

    event OrderCreated(address indexed user, uint256 amount);
    event OrderFinished(address indexed user, uint256 amount, uint256 reward);
    event RewardClaimed(address indexed user, uint256 reward);
    event NodeRewardClaimed(address indexed user, uint256 reward);
    event LevelRewardClaimed(address indexed user, uint256 reward);
    event StaticRewardClaimed(address indexed user, uint256 reward);
    event DynamicRewardClaimed(address indexed user, uint256 reward);

    error InvalidAmount();
    error UserNotBinded();
    error HasUnfinishedOrder();
    error NoRewards();

    constructor(
        address _recipient,
        address _usdt,
        address _token,
        address _relationship,
        address _node,
        address _vault,
        address _router,
        address _poolV1,
        address _approveProxy
    ) Ownable(msg.sender) {
        recipient = _recipient;
        usdt = _usdt;
        token = _token;
        relationship = _relationship;
        node = _node;
        vault = _vault;
        router = _router;
        poolV1 = _poolV1;
        approveProxy = _approveProxy;

        amountMin = 100 * 1e6;
        amountMax = 2000 * 1e6;
        rewardRate = 14000;
        rewardRatePreDay = (1e6 * 7000 * 180) / BASE / BASE;
        depthMax = 15;

        configs[1] = Config(2 * 1e4 * 1e6, 1000);
        configs[2] = Config(10 * 1e4 * 1e6, 2000);
        configs[3] = Config(30 * 1e4 * 1e6, 3000);
        configs[4] = Config(60 * 1e4 * 1e6, 4000);
        configs[5] = Config(100 * 1e4 * 1e6, 5000);

        pair = IPoolV1(poolV1).pair();
    }

    function setRecipient(address _recipient) public onlyOwner {
        recipient = _recipient;
    }

    function setUsdt(address _usdt) public onlyOwner {
        usdt = _usdt;
    }

    function setToken(address _token) public onlyOwner {
        token = _token;
    }

    function setRelationship(address _relationship) public onlyOwner {
        relationship = _relationship;
    }

    function setNode(address _node) public onlyOwner {
        node = _node;
    }

    function setVault(address _vault) public onlyOwner {
        vault = _vault;
    }

    function setRouter(address _router) public onlyOwner {
        router = _router;
    }

    function setPair(address _pair) public onlyOwner {
        pair = _pair;
    }

    function setAmountMin(uint256 _amountMin) public onlyOwner {
        amountMin = _amountMin;
    }

    function setAmountMax(uint256 _amountMax) public onlyOwner {
        amountMax = _amountMax;
    }

    function setRewardRate(uint256 _rewardRate) public onlyOwner {
        rewardRate = _rewardRate;
    }

    function setRewardRatePreDay(uint256 _rewardRatePreDay) public onlyOwner {
        rewardRatePreDay = _rewardRatePreDay;
    }

    function setDepthMax(uint256 _depthMax) public onlyOwner {
        depthMax = _depthMax;
    }

    function setConfig(uint256 _index, uint256 _performance, uint256 _rewardRate) public onlyOwner {
        configs[_index] = Config(_performance, _rewardRate);
    }

    function price() public view returns (uint256) {
        address token0 = IUniswapV2Pair(pair).token0();
        (uint112 reserve0, uint112 reserve1, ) = IUniswapV2Pair(pair).getReserves();
        if (token0 == token) {
            return (uint256(reserve1) * 1e4) / uint256(reserve0);
        } else {
            return (uint256(reserve0) * 1e4) / uint256(reserve1);
        }
    }

    function getOrder(address user) public view returns (Order memory) {
        Order memory order = orders[user];
        if (order.amount == 0) {
            Order memory orderV1 = IPoolV1(poolV1).orders(user);
            if (orderV1.amount != 0) {
                order = orderV1;
            }
        }
        return order;
    }

    function getPerformance(address user) public view returns (uint256) {
        uint256 performance = performances[user];
        if (performances[user] == 0) {
            uint256 performanceV1 = IPoolV1(poolV1).performances(user);
            if (performanceV1 != 0) {
                performance = performanceV1;
            }
        }
        return performance;
    }

    function getLevel(address user) public view returns (uint256) {
        uint256 level = levels[user];
        if (level == 0) {
            uint256 levelV1 = IPoolV1(poolV1).levels(user);
            if (levelV1 != 0) {
                level = levelV1;
            }
        }

        if (INode(node).nodes(user) == true && level < 2) {
            level = 2;
        }
        return level;
    }

    function earned(address user) public view returns (uint256) {
        Order memory order = orders[user];
        if (order.amount == 0) {
            Order memory orderV1 = IPoolV1(poolV1).orders(user);
            if (orderV1.amount != 0) {
                order = orderV1;
            }
        }

        uint256 time;
        if (order.claimedTime == 0) {
            time = block.timestamp - order.createdTime;
        } else {
            time = block.timestamp - order.claimedTime;
        }
        uint256 reward = (order.amount * rewardRatePreDay * time) / 1e6 / 1 days;
        if (reward > order.totalReward - order.claimedReward) {
            reward = order.totalReward - order.claimedReward;
        }
        return reward;
    }

    function mint(uint256 amount) public {
        if (amount < amountMin || amount > amountMax) revert InvalidAmount();

        Order memory order = orders[msg.sender];
        if (order.amount == 0) {
            Order memory orderV1 = IPoolV1(poolV1).orders(msg.sender);
            if (orderV1.amount != 0) {
                order = orderV1;
            }
        }

        if (order.running == true) revert HasUnfinishedOrder();
        if (IRelationship(relationship).hasBinded(msg.sender) == false) revert UserNotBinded();

        IApproveProxy(approveProxy).claim(usdt, msg.sender, address(this), amount);

        IERC20(usdt).safeTransfer(vault, (amount * 8000) / BASE);

        uint256 reward = (amount * 500) / BASE;
        IERC20(usdt).safeTransfer(token, reward);
        IToken(token).notifyRewardAmount(reward);

        _nodeReward(msg.sender, amount, 0);

        orders[msg.sender] = Order(amount, (amount * rewardRate) / BASE, block.timestamp, 0, 0, true);

        _updatePerformance(msg.sender, amount, 0);

        emit OrderCreated(msg.sender, amount);
    }

    function getReward() public {
        uint256 reward = earned(msg.sender);
        if (reward == 0) revert NoRewards();

        Order storage order = orders[msg.sender];
        if (order.amount == 0) {
            Order memory orderV1 = IPoolV1(poolV1).orders(msg.sender);
            if (orderV1.amount != 0) {
                order.amount = orderV1.amount;
                order.totalReward = orderV1.totalReward;
                order.createdTime = orderV1.createdTime;
                order.claimedTime = orderV1.claimedTime;
                order.claimedReward = orderV1.claimedReward;
                order.running = orderV1.running;
            }
        }

        order.claimedTime = block.timestamp;
        _updateOrder(order, reward);
        if (order.running == false) {
            emit OrderFinished(msg.sender, order.amount, order.totalReward);
        }

        IVault(vault).transfer(usdt, pair, (reward * BASE * BASE) / 70000 / 18000);
        IUniswapV2Router(router).sync(pair);

        uint256 amount = (reward * 1e4) / price();

        IVault(vault).transfer(usdt, pair, reward);
        IVault(vault).transfer(token, pair, amount);
        IUniswapV2Router(router).sync(pair);

        IVault(vault).transfer(token, msg.sender, amount);
        emit RewardClaimed(msg.sender,amount);

        _reward(msg.sender, reward, 0, 0);
    }

    function _updatePerformance(address user, uint256 amount, uint256 depth) private {
        depth++;
        if (depth > depthMax) return;

        address referrer = IRelationship(relationship).referrers(user);
        if (referrer == IRelationship(relationship).ROOT()) return;

        if (performances[referrer] == 0) {
            uint256 performanceV1 = IPoolV1(poolV1).performances(referrer);
            if (performanceV1 != 0) {
                performances[referrer] = performanceV1;
            }
        }

        performances[referrer] += amount;

        _updateLevel(referrer);

        _updatePerformance(referrer, amount, depth);
    }

    function _updateLevel(address user) private {
        uint256 level = levels[user];
        if (level == 0) {
            uint256 levelV1 = IPoolV1(poolV1).levels(user);
            if (levelV1 != 0) {
                levels[user] = levelV1;
            }
        }

        if (performances[user] == 0) {
            uint256 performanceV1 = IPoolV1(poolV1).performances(user);
            if (performanceV1 != 0) {
                performances[user] = performanceV1;
            }
        }

        uint256 performance = configs[level + 1].performance;
        if (performance > 0 && performances[user] >= performance) {
            levels[user]++;
            _updateLevel(user);
        }
    }

    function _reward(address user, uint256 amount, uint256 depth, uint256 take) private {
        address referrer = IRelationship(relationship).referrers(user);
        if (referrer == IRelationship(relationship).ROOT()) return;

        if (depth == 0) {
            _staticReward(referrer, amount);
        }

        take = _dynamicReward(referrer, amount, take);

        depth++;
        if (depth == depthMax) return;

        _reward(referrer, amount, depth, take);
    }

    function _staticReward(address user, uint256 amount) private {
        Order storage order = orders[user];
        if (order.amount == 0) {
            Order memory orderV1 = IPoolV1(poolV1).orders(user);
            if (orderV1.amount != 0) {
                order.amount = orderV1.amount;
                order.totalReward = orderV1.totalReward;
                order.createdTime = orderV1.createdTime;
                order.claimedTime = orderV1.claimedTime;
                order.claimedReward = orderV1.claimedReward;
                order.running = orderV1.running;
            }
        }

        if (order.running) {
            uint256 reward = (amount * 1000) / BASE;
            if (reward > order.totalReward - order.claimedReward) {
                reward = order.totalReward - order.claimedReward;
            }
            _updateOrder(order, reward);
            if (order.running == false) {
                emit OrderFinished(user, order.amount, order.totalReward);
            }
            IVault(vault).transfer(token, user, (reward * 1e4) / price());
            emit StaticRewardClaimed(user,(reward * 1e4) / price());
        }
    }

    function _dynamicReward(address user, uint256 amount, uint256 take) private returns (uint256) {
        Order storage order = orders[user];
        if (order.amount == 0) {
            Order memory orderV1 = IPoolV1(poolV1).orders(user);
            if (orderV1.amount != 0) {
                order.amount = orderV1.amount;
                order.totalReward = orderV1.totalReward;
                order.createdTime = orderV1.createdTime;
                order.claimedTime = orderV1.claimedTime;
                order.claimedReward = orderV1.claimedReward;
                order.running = orderV1.running;
            }
        }

        if (order.running) {
            uint256 reward = (amount * configs[getLevel(user)].rewardRate) / BASE;
            if (reward > take) {
                reward = reward - take;
                if (reward > order.totalReward - order.claimedReward) {
                    reward = order.totalReward - order.claimedReward;
                }
                _updateOrder(order, reward);
                if (order.running == false) {
                    emit OrderFinished(user, order.amount, order.totalReward);
                }
                IVault(vault).transfer(token, user, (reward * 1e4) / price());
                emit DynamicRewardClaimed(user, (reward * 1e4) / price());

                take += reward;

                _levelReward(user, reward);
            }
        }

        return take;
    }

    function _levelReward(address user, uint256 amount) private {
        address referrer = IRelationship(relationship).referrers(user);
        if (referrer == IRelationship(relationship).ROOT()) return;

        if (getLevel(user) != getLevel(referrer)) return;

        Order storage order = orders[referrer];
        if (order.amount == 0) {
            Order memory orderV1 = IPoolV1(poolV1).orders(referrer);
            if (orderV1.amount != 0) {
                order.amount = orderV1.amount;
                order.totalReward = orderV1.totalReward;
                order.createdTime = orderV1.createdTime;
                order.claimedTime = orderV1.claimedTime;
                order.claimedReward = orderV1.claimedReward;
                order.running = orderV1.running;
            }
        }

        if (order.running) {
            uint256 reward = (amount * 2000) / BASE;
            if (reward > order.totalReward - order.claimedReward) {
                reward = order.totalReward - order.claimedReward;
            }
            _updateOrder(order, reward);
            if (order.running == false) {
                emit OrderFinished(referrer, order.amount, order.totalReward);
            }
            IVault(vault).transfer(token, referrer, (reward * 1e4) / price());
            emit LevelRewardClaimed(referrer, (reward * 1e4) / price());
        }
    }

    function _nodeReward(address user, uint256 amount, uint256 depth) private {
        uint256 reward = (amount * 1500) / BASE;
        address referrer = IRelationship(relationship).referrers(user);
        if (referrer == IRelationship(relationship).ROOT()) {
            IERC20(usdt).safeTransfer(recipient, reward);
            return;
        }

        if (INode(node).nodes(referrer) == true) {
            IERC20(usdt).safeTransfer(referrer, reward);
            emit NodeRewardClaimed(referrer, reward);
            return;
        }

        depth++;
        if (depth == depthMax) {
            IERC20(usdt).safeTransfer(recipient, reward);
            return;
        }
        _nodeReward(referrer, amount, depth);
    }

    function _updateOrder(Order storage order, uint256 amount) private {
        order.claimedReward += amount;
        if (order.claimedReward == order.totalReward) {
            order.running = false;
        }
    }
}
