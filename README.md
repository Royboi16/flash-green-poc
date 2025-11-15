# flash-green-poc

## Configuration

Environment variables can be stored in a local `.env` file (loaded automatically).
When running the on-chain flash-loan path (`USE_WEB3_LOAN=1`) ensure the RPC
endpoint is supplied via `HARDHAT_RPC`. For example:

```
HARDHAT_RPC=http://127.0.0.1:8545
FLASH_LOAN_CONTRACT=0xYourFlashLoanContract
FLASH_LOAN_RECEIVER=0xYourReceiverContract
LENDER_KEY=0xyourPrivateKey
USE_WEB3_LOAN=1
```

Point `HARDHAT_RPC` at whichever Hardhat, Anvil, or mainnet/Goerli JSON-RPC
endpoint you plan to use.
