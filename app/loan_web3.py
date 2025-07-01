from web3 import Web3
import os

# Hardhat default RPC
RPC_URL = os.getenv("HARDHAT_RPC", "http://127.0.0.1:8545")
w3 = Web3(Web3.HTTPProvider(RPC_URL))

# ABI snippet for FlashLoan.flashLoan and TestReceiver
FLASH_LOAN_ABI = [
    # constructor, flashLoan, fallback
    {"inputs":[{"internalType":"uint256","name":"_feeBps","type":"uint256"}],"stateMutability":"nonpayable","type":"constructor"},
    {"inputs":[{"internalType":"address","name":"receiver","type":"address"},{"internalType":"uint256","name":"amount","type":"uint256"}],"name":"flashLoan","outputs":[],"stateMutability":"nonpayable","type":"function"}
]

class Web3FlashLoan:
    def __init__(self, lender_address, private_key):
        self.account = w3.eth.account.from_key(private_key)
        self.lender = w3.eth.contract(address=lender_address, abi=FLASH_LOAN_ABI)

    def flash_loan(self, receiver_address, amount_wei):
        tx = self.lender.functions.flashLoan(receiver_address, amount_wei).buildTransaction({
            "from": self.account.address,
            "gas": 300_000,
            "nonce": w3.eth.get_transaction_count(self.account.address),
            "chainId": 1337
        })
        signed = self.account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        return receipt


