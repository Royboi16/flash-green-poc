// SPDX-License-Identifier: MIT
pragma solidity ^0.8.21;

interface IFlashLoan {
    /// @notice feeBps is exposed by FlashLoan
    function feeBps() external view returns (uint256);
}

contract TestReceiver {
    address public lender;

    constructor(address _lender) {
        lender = _lender;
    }

    /// @notice Allow receiving the principal
    receive() external payable {}

    /// @notice This is called by FlashLoan.flashLoan(...)
    /// @param amount The borrowed amount
    /// @param _feeBps The fee basis points (same as lender.feeBps())
    function executeOnLoan(uint256 amount, uint256 _feeBps) external payable {
        // compute the fee
        uint256 fee = (amount * _feeBps) / 10_000;

        // repay principal + fee back to lender
        (bool sent, ) = payable(lender).call{value: amount + fee}("");
        require(sent, "Repayment failed");
    }
}