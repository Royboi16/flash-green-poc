// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract FlashLoan {
    address public owner;
    uint256 public feeBps;      // basis points fee, e.g. 5 = 0.05%

    constructor(uint256 _feeBps) {
        owner   = msg.sender;
        feeBps  = _feeBps;
    }

    /// @notice Execute a flash-loan: receiverContract must implement executeOnLoan()
    function flashLoan(address receiver, uint256 amount) external {
        uint256 balanceBefore = address(this).balance;
        require(balanceBefore >= amount, "Not enough liquidity");

        // send funds
        (bool sent,) = receiver.call{value: amount}("");
        require(sent, "Loan transfer failed");

        // callback
        IFlashLoanReceiver(receiver).executeOnLoan{value:0}(amount, feeBps);

        // compute repayment
        uint256 fee    = (amount * feeBps) / 10_000;
        uint256 repay  = amount + fee;
        uint256 balanceAfter = address(this).balance;
        require(balanceAfter >= balanceBefore + fee, "Loan not repaid with fee");
    }

    // allow deposits
    receive() external payable {}
}

interface IFlashLoanReceiver {
    function executeOnLoan(uint256 amount, uint256 feeBps) external payable;
}
