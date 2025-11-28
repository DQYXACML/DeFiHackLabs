// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import {Collector, ICollector} from 'aave-v3-origin/contracts/treasury/Collector.sol';

/**
 * @title Collector
 * Custom modifications of this implementation:
 * - the initialize function manually alters private storage slots via assembly
 * - storage slot 0 (previously revision) is reset to zero
 * - storage slot 51 (previously _status) is set to zero
 * - storage slot 52 (previously _fundsAdmin) is set to zero
 * @author BGD Labs
 *
 */
contract CollectorWithCustomImpl is Collector {
  function initialize(uint256, address admin) external virtual override initializer {
    assembly {
      sstore(0, 0) // this slot was revision, which is no longer used
      sstore(51, 0) // this slot was _status, but is now part of the gap
      sstore(52, 0) // this slot was _fundsAdmin, but is now unused
    }
    __AccessControl_init();
    __ReentrancyGuard_init();
    _grantRole(DEFAULT_ADMIN_ROLE, admin);
  }
}
