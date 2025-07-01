// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "./FlashLoan.sol";

contract TestReceiver is IFlashLoanReceiver {
    address public lender;
    event Executed(uint256 amount, uint256 fee);

    constructor(address _lender) {
        lender = _lender;
    }

    // receive loan, do nothing, repay amount+fee back to lender
    function executeOnLoan(uint256 amount, uint256 feeBps) external payable override {
        uint256 fee = (amount * feeBps) / 10_000;
        uint256 repay = amount + fee;
        // repay lender
        (bool sent,) = payable(lender).call{value: repay}("");
        require(sent, "Repay failed");
        emit Executed(amount, fee);
    }

    // helper to fund contract
    function fund() external payable {}
}
