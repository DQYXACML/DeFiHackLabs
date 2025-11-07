//SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.0;

import "./ERC404.sol";
import "./strings.sol";

contract EGGX is ERC404 {
    string public dataURI;
    string public baseTokenURI;

    constructor(address _owner) ERC404("EGGX", "EGGX", 18, 100000000, _owner) {
        balanceOf[_owner] = 100000000 * 10 ** 18;
    } 

    function setDataURI(string memory _dataURI) public onlyOwner {
        dataURI = _dataURI;
    }

    function setTokenURI(string memory _tokenURI) public onlyOwner {
        baseTokenURI = _tokenURI;
    }

    function setNameSymbol(
        string memory _name,
        string memory _symbol
    ) public onlyOwner {
        _setNameSymbol(_name, _symbol);
    }

    function _getImage(uint256 id) internal pure returns (string memory, string memory, string memory, string memory) {
        uint8 seed1 = uint8(bytes1(keccak256(abi.encodePacked(id))));
        uint8 seed2 = uint8(bytes1(keccak256(abi.encodePacked(id + 101))));
        uint8 seed3 = uint8(bytes1(keccak256(abi.encodePacked(id + 202))));
        
        
        string memory color;
        string memory pattern;
        string memory wings;

        if (seed1 <= 13) {
            // 5 / 100 * 255 = 13
            pattern = "scale";
        } else if (seed1 <= 33) {
            // 13 / 100 * 255 = 33
            pattern = "nebula";
        } else if (seed1 <= 61) {
            // 24 / 100 * 255 = 61
            pattern = "star";
        } else if (seed1 <= 97) {
            // 38 / 100 * 255 = 97
            pattern = "cloud";
        } else if (seed1 <= 140) {
            // 55 / 100 * 255 = 140
            pattern = "mountain";
        } else if (seed1 <= 194) {
            // 76 / 100 * 255 = 194
            pattern = "river";
        } else {
            pattern = "flower";
        }
        
        if (seed2 <= 56) {
            color = "red";
        } else if (seed2 <= 107 ) {
            color = "blue";
        } else if (seed2 <= 153 ) {
            color = "green";
        } else if (seed2 <= 194) {
            color = "yellow";
        } else if (seed2 <= 227) {
            color = "black";
        } else {
            color = "camouflage";
        }

        if (seed3 <= 204) {
            wings = "wingless";
        } else {
            wings = "winged";
        }

        string memory _t1 = string.concat('egg-', pattern);
        string memory _t2 = string.concat(_t1, color);
        string memory _t3 = string.concat(_t2, wings);

        string memory image = string.concat(_t3, '.jpg');
        return (image, color, pattern, wings);
    }

    function tokenURI(uint256 id) public view override returns (string memory) {
        if (bytes(baseTokenURI).length > 0) {
            return string.concat(baseTokenURI, Strings.toString(id));
        } else {
            string memory image;
            string memory color;
            string memory pattern;
            string memory wings;

            (image, color, pattern, wings) = _getImage(id);

            string memory jsonPreImage = string.concat(
                string.concat(
                    string.concat('{"name": "EGGX #', Strings.toString(id)),
                    '","description":"A collection of 10,000 EGGX NFTs enabled by an adjustedversion of ERC404, an experimental token standardenabling persistent liquidity and semi-fungibility forEthereum NFTs.","external_url":"https://eggs.build","image":"'
                ),
                string.concat(dataURI, image)
            );
            string memory jsonPostImage = string.concat(
                '","attributes":[{"trait_type":"Color","value":"',
                color
            );
            string memory jsonPostImage1 = string.concat(
                '"},{"trait_type":"Pattern","value":"',
                pattern
            );
            
            string memory j1 = string.concat(jsonPostImage, jsonPostImage1);

            string memory jsonPostImage2 = string.concat(
                '"},{"trait_type":"Wings","value":"',
                wings
            );

            string memory j2 = string.concat(j1, jsonPostImage2);

            string memory jsonPostTraits = '"}]}';

            return
                string.concat(
                    "data:application/json;utf8,",
                    string.concat(
                        string.concat(jsonPreImage, j2),
                        jsonPostTraits
                    )
                );
        }
    }
}
