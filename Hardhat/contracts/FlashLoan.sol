// hardhat/contracts/FlashLoan.sol
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

interface IFlashLoanReceiver {
    function executeOnLoan(uint256 amount, uint256 feeBps) external payable;
}

contract FlashLoan {
    address public owner;
    uint256 public feeBps;      // basis points fee, e.g. 5 = 0.05%

    constructor(uint256 _feeBps) {
        owner   = msg.sender;
        feeBps  = _feeBps;
    }

    /// @notice helper: compute the fee for a given amount
    function feeFor(uint256 amount) public view returns (uint256) {
        return (amount * feeBps) / 10_000;
    }

    /// @notice Execute a flash-loan: receiver must implement executeOnLoan()
    function flashLoan(address receiver, uint256 amount) external {
        uint256 balanceBefore = address(this).balance;
        require(balanceBefore >= amount, "Not enough liquidity");

        // FIX: Combine the value transfer and function call into one.
        // This transfers the loan amount and immediately invokes the receiver's logic.
        IFlashLoanReceiver(receiver).executeOnLoan{value: amount}(amount, feeBps);

        // check repayment
        uint256 fee = feeFor(amount);
        require(address(this).balance >= balanceBefore + fee, "Loan not repaid with fee");
    }

    // allow deposits
    receive() external payable {}
}