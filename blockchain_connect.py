from web3 import Web3
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Ethereum RPC configuration
# Option 1: Use Infura (set in .env: INFURA_API_KEY)
# Option 2: Use Alchemy (set in .env: ALCHEMY_API_KEY)
# Option 3: Use custom RPC URL (set in .env: ETH_RPC_URL)

infura_key = os.getenv("INFURA_API_KEY", "")
alchemy_key = os.getenv("ALCHEMY_API_KEY", "")
custom_rpc = os.getenv("ETH_RPC_URL", "")

if custom_rpc:
    ethereum_rpc = custom_rpc
elif infura_key:
    ethereum_rpc = f"https://mainnet.infura.io/v3/{infura_key}"
elif alchemy_key:
    ethereum_rpc = f"https://eth-mainnet.g.alchemy.com/v2/{alchemy_key}"
else:
    # Default to public Ethereum RPC
    ethereum_rpc = "https://eth.llamarpc.com"

web3 = Web3(Web3.HTTPProvider(ethereum_rpc))

print("Ethereum RPC URL:", ethereum_rpc)
print("Connected:", web3.is_connected())