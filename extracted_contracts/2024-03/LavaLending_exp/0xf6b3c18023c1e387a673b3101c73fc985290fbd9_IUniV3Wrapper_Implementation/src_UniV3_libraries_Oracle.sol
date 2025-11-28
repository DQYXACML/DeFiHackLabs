// SPDX-License-Identifier: Unlicensed
pragma solidity 0.8;

import "../interfaces/IUniV3Pool.sol";

library Oracle {
    /// @notice Returns the maximum observation period of the pool.
    function getMaxObservationPeriod(IUniV3Pool pool) internal view returns (uint32 maxSecondsAgo) {
        (,, uint16 observationIndex, uint16 observationCardinality,,,) = pool.slot0();
        uint16 oldestIndex = observationIndex == 0 ? observationCardinality + 1 : observationIndex + 1;
        (uint32 oldestBlockTimestamp,,,) = pool.observations(oldestIndex);
        if (oldestBlockTimestamp == 1) {
            (oldestBlockTimestamp,,,) = pool.observations(0);
        }
        maxSecondsAgo = uint32(block.timestamp - oldestBlockTimestamp);
    }

    /// @notice Returns the moving average tick of the pool, given the period.
    function getMovingAverage(IUniV3Pool pool, uint32 period) internal view returns (int24 tick) {
        uint32 max = getMaxObservationPeriod(pool);
        if (period > max) period = max;
        if (period == 0) {
            (, tick,,,,,) = pool.slot0();
        } else {
            uint32[] memory observations = new uint32[](2);
            observations[0] = period;
            observations[1] = 0;
            (int56[] memory tickCumulatives,) = pool.observe(observations);
            tick = int24((tickCumulatives[1] - tickCumulatives[0]) / int56(uint56(period)));
        }
    }
}
