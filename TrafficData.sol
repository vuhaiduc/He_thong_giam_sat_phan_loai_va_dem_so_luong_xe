// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract TrafficData {
    struct TrafficRecord {
        uint256 lane;
        uint256 car;
        uint256 truck;
        uint256 total;
        uint256 up;
        uint256 down;
        string timestamp;
    }

    TrafficRecord[] public trafficList;

    function addTrafficData(
        uint256 _lane,
        uint256 _car,
        uint256 _truck,
        uint256 _total,
        uint256 _up,
        uint256 _down,
        string memory _timestamp
    ) public {
        trafficList.push(
            TrafficRecord(
                _lane,
                _car,
                _truck,
                _total,
                _up,
                _down,
                _timestamp
            )
        );
    }

    function getTrafficCount() public view returns (uint256) {
        return trafficList.length;
    }
}
