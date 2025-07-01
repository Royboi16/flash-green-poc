require("@nomicfoundation/hardhat-toolbox");

module.exports = {
  solidity: "0.8.20",
  networks: {
    hardhat: {
      chainId: 1337
    }
  },
  paths: {
    sources: "contracts",
    tests:   "../tests/hardhat",
    cache:   "cache",
    artifacts: "artifacts"
  }
};
