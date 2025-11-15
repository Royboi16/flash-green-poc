# app/loan_web3.py

import os
from typing import Optional, Tuple, Dict

from web3 import Web3, HTTPProvider
from web3.middleware import geth_poa_middleware

# ABI snippet for FlashLoan.flashLoan
FLASH_LOAN_ABI = [
    {"inputs": [{"internalType": "uint256", "name": "_feeBps", "type": "uint256"}], "stateMutability": "nonpayable", "type": "constructor"},
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

RECEIVER_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "fee", "type": "uint256"},
        ],
        "name": "Executed",
        "type": "event",
    }
]

NETWORK_RPC_ENV = {
    "hardhat": "HARDHAT_RPC",
    "anvil": "ANVIL_RPC_URL",
    "sepolia": "SEPOLIA_RPC_URL",
    "mainnet": "MAINNET_RPC_URL",
}


class Web3FlashLoan:
    def __init__(
        self,
        lender_address: str,
        private_key: str,
        *,
        network: str = "hardhat",
        rpc_url: Optional[str] = None,
    ):
        # 1) resolve RPC endpoint
        self.network = network
        env_var = NETWORK_RPC_ENV.get(network)
        endpoint = rpc_url or os.getenv("FLASH_LOAN_RPC_URL")
        if not endpoint and env_var:
            endpoint = os.getenv(env_var)
        if not endpoint:
            raise ValueError(f"Missing RPC URL for network '{network}'")

        self.w3 = Web3(HTTPProvider(endpoint))
        if network in {"sepolia", "mainnet"}:
            self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        if not self.w3.is_connected():
            raise ConnectionError(f"Unable to connect to RPC at {endpoint}")

        self.chain_id = self.w3.eth.chain_id
        self.account = self.w3.eth.account.from_key(private_key)
        self.lender = self.w3.eth.contract(address=lender_address, abi=FLASH_LOAN_ABI)
        self._nonce = self.w3.eth.get_transaction_count(self.account.address)

    def _next_nonce(self) -> int:
        nonce = self._nonce
        self._nonce += 1
        return nonce

    def flash_loan(
        self,
        *,
        receiver_address: str,
        amount_wei: int,
        expected_fee_bps: float = 0.0,
    ) -> Tuple[Dict[str, int], Dict[str, int]]:
        """Execute a flash-loan and decode the receiver's Executed event."""
        tx = self.lender.functions.flashLoan(receiver_address, amount_wei).build_transaction(
            {
                "from": self.account.address,
                "nonce": self._next_nonce(),
                "gas": 400_000,
                "gasPrice": self.w3.eth.gas_price,
                "chainId": self.chain_id,
            }
        )

        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status != 1:
            raise RuntimeError("Flash-loan transaction reverted")

        receiver = self.w3.eth.contract(address=receiver_address, abi=RECEIVER_ABI)
        logs = receiver.events.Executed().process_receipt(receipt)
        if not logs:
            raise RuntimeError("Receiver did not emit Executed event")
        event_args = logs[-1]["args"]
        amount_logged = int(event_args["amount"])
        fee_logged = int(event_args["fee"])

        if amount_logged != int(amount_wei):
            raise RuntimeError(
                f"Receiver amount mismatch (expected {amount_wei}, got {amount_logged})"
            )
        expected_fee = int((amount_wei * expected_fee_bps) / 10_000)
        if expected_fee and fee_logged != expected_fee:
            raise RuntimeError(
                f"Receiver fee mismatch (expected {expected_fee}, got {fee_logged})"
            )

        decoded = {"amount": amount_logged, "fee": fee_logged}
        meta = {
            "status": receipt.status,
            "blockNumber": receipt.blockNumber,
            "transactionHash": receipt.transactionHash.hex(),
        }
        return meta, decoded
