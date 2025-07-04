# app/loan_web3.py

import os
from web3 import Web3, HTTPProvider

# ABI snippet for FlashLoan.flashLoan
FLASH_LOAN_ABI = [
    # constructor(uint256 _feeBps)
    {
        "inputs": [
            {"internalType": "uint256", "name": "_feeBps", "type": "uint256"}
        ],
        "stateMutability": "nonpayable",
        "type": "constructor",
    },
    # flashLoan(address receiver, uint256 amount)
    {
        "inputs": [
            {"internalType": "address", "name": "receiver", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
        ],
        "name": "flashLoan",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


class Web3FlashLoan:
    def __init__(self, lender_address: str, private_key: str, rpc_url: str):
        # 1) connect to the node
        self.w3 = Web3(HTTPProvider(rpc_url))
        if not self.w3.is_connected():
            raise ConnectionError(f"Unable to connect to RPC at {rpc_url}")

        # 2) read the actual chain ID (Hardhat defaults to 31337)
        self.chain_id = self.w3.eth.chain_id

        # 3) set up our account and contract
        self.account = self.w3.eth.account.from_key(private_key)
        self.lender  = self.w3.eth.contract(address=lender_address, abi=FLASH_LOAN_ABI)

    def flash_loan(self, receiver_address: str, amount_wei: int):
        # build the transaction
        tx = self.lender.functions.flashLoan(receiver_address, amount_wei).build_transaction({
            "from":     self.account.address,
            "nonce":    self.w3.eth.get_transaction_count(self.account.address),
            "gas":      300_000,
            "gasPrice": self.w3.eth.gas_price,
            "chainId":  self.chain_id,
        })

        # sign & send
        signed  = self.account.sign_transaction(tx)
        raw     = signed.raw_transaction
        tx_hash = self.w3.eth.send_raw_transaction(raw)

        # wait for it to be mined
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        return receipt
