/*
        [....     [... [......  [.. ..
      [..    [..       [..    [..    [..
    [..        [..     [..     [..         [..       [..
    [..        [..     [..       [..     [.   [..  [..  [..
    [..        [..     [..          [.. [..... [..[..   [..
      [..     [..      [..    [..    [..[.        [..   [..
        [....          [..      [.. ..    [....     [.. [...

    https://otsea.io
    https://t.me/OTSeaPortal
    https://twitter.com/OTSeaERC20
*/

// SPDX-License-Identifier: MIT
pragma solidity =0.8.20;

/// @title Common OTSea variables
library OTSeaLibrary {
    enum FeeType {
        Fish,
        Whale
    }

    uint16 internal constant PERCENT_DENOMINATOR = 10000;
    address internal constant DEAD_ADDRESS = address(0xdead);
}
