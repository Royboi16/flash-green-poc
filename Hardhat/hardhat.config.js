// hardhat/hardhat.config.js
require("@nomicfoundation/hardhat-toolbox");

module.exports = {
  solidity: "0.8.21",
  // no defaultNetwork here — let Hardhat default to "hardhat"
  networks: {
    // define your localhost network so "--network localhost" works
    localhost: {
      url: "http://127.0.0.1:8545",
    },
  },
};