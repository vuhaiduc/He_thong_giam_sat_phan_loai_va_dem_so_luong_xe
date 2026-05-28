from web3 import Web3
import hashlib
import json
import time
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Ethereum RPC configuration
infura_key = os.getenv("INFURA_API_KEY", "")
alchemy_key = os.getenv("ALCHEMY_API_KEY", "")
custom_rpc = os.getenv("ETH_RPC_URL", "")
contract_address_env = os.getenv("CONTRACT_ADDRESS", "").strip()

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

print("Connected:", web3.is_connected())
print("Ethereum RPC URL:", ethereum_rpc)
if web3.is_connected():
    print("Chain ID:", web3.eth.chain_id)
    print("Available accounts:", web3.eth.accounts[:3] if web3.eth.accounts else "None")

contract_address = Web3.to_checksum_address(
    contract_address_env or "0x51480F4518a1990e367d8Cc54514a1ECcC6d8d59"
)
print(f"Contract address: {contract_address}")

abi = json.loads('''
[
    {
        "inputs": [
            {"internalType": "uint256", "name": "_lane", "type": "uint256"},
            {"internalType": "uint256", "name": "_car", "type": "uint256"},
            {"internalType": "uint256", "name": "_truck", "type": "uint256"},
            {"internalType": "uint256", "name": "_total", "type": "uint256"},
            {"internalType": "uint256", "name": "_up", "type": "uint256"},
            {"internalType": "uint256", "name": "_down", "type": "uint256"},
            {"internalType": "string", "name": "_timestamp", "type": "string"}
        ],
        "name": "addTrafficData",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "getTrafficCount",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "name": "trafficList",
        "outputs": [
            {"internalType": "uint256", "name": "lane", "type": "uint256"},
            {"internalType": "uint256", "name": "car", "type": "uint256"},
            {"internalType": "uint256", "name": "truck", "type": "uint256"},
            {"internalType": "uint256", "name": "total", "type": "uint256"},
            {"internalType": "uint256", "name": "up", "type": "uint256"},
            {"internalType": "uint256", "name": "down", "type": "uint256"},
            {"internalType": "string", "name": "timestamp", "type": "string"}
        ],
        "stateMutability": "view",
        "type": "function"
    }
]
''')

account = None
private_key = os.getenv("PRIVATE_KEY", "")

if private_key:
    try:
        # Import account from private key
        account = web3.eth.account.from_key(private_key)
        print(f"\n✅ Account loaded from private key: {account.address}")
    except Exception as e:
        print(f"\n❌ Failed to load account from PRIVATE_KEY: {e}")
else:
    print("\n⚠️  PRIVATE_KEY not set. Read-only mode (get_traffic_data only).")
    print("   To send transactions, set: export PRIVATE_KEY='your_private_key'")

current_code = web3.eth.get_code(contract_address)
if len(current_code) == 0:
    print("\n❌ Contract address has no bytecode.")
    print("   Vui long deploy trong Remix va cap nhat lai contract_address.")
else:
    print(f"\n✅ Contract found! Bytecode: {len(current_code)} bytes")

# Always use the manual address declared above (no auto-deploy, no self-modify).
contract = web3.eth.contract(address=contract_address, abi=abi)
print(f"✅ Contract ready at: {contract_address}")

# Short-term in-memory cache to reduce RPC calls during verification
# Keeps recent count and individual items for CACHE_TTL seconds.
CACHE_TTL = 5.0  # seconds
_chain_cache = {
    'timestamp': 0.0,
    'count': None,
    'items': {},  # index -> item dict
}


def _update_cache_count(count):
    _chain_cache['timestamp'] = time.time()
    _chain_cache['count'] = count


def _update_cache_item(index, item):
    _chain_cache['timestamp'] = time.time()
    _chain_cache['items'][index] = item


def get_traffic_count(retries=3, retry_delay=0.5):
    """Return traffic count (number of items). Uses short-term cache if fresh."""
    now = time.time()
    if _chain_cache.get('count') is not None and (now - _chain_cache.get('timestamp', 0)) < CACHE_TTL:
        return _chain_cache['count']

    for attempt in range(retries):
        try:
            count = contract.functions.getTrafficCount().call()
            _update_cache_count(count)
            return count
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(retry_delay)
            else:
                return None


def get_traffic_item(index, retries=3, retry_delay=0.5):
    """Fetch a single trafficList item by index with retries and cache it.

    Returns dict or None on failure.
    """
    now = time.time()
    # Use cached item if present and fresh
    if index in _chain_cache.get('items', {}) and (now - _chain_cache.get('timestamp', 0)) < CACHE_TTL:
        return _chain_cache['items'][index]

    for attempt in range(retries):
        try:
            item = contract.functions.trafficList(index).call()
            result = {
                "lane": item[0],
                "car": item[1],
                "truck": item[2],
                "total": item[3],
                "up": item[4],
                "down": item[5],
                "timestamp": item[6],
            }
            _update_cache_item(index, result)
            return result
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(retry_delay)
            else:
                return None



def send_traffic_data(lane, car, truck, total, up, down, timestamp=None):
    try:
        if account is None:
            raise RuntimeError("Ethereum account is unavailable")

        if timestamp is None:
            timestamp = time.strftime("%H:%M:%S")

        payload = {
            "lane": int(lane),
            "car": int(car),
            "truck": int(truck),
            "total": int(total),
            "up": int(up),
            "down": int(down),
            "timestamp": timestamp,
        }
        payload_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=True)
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

        # Build the transaction
        tx_dict = contract.functions.addTrafficData(
            int(lane),
            int(car),
            int(truck),
            int(total),
            int(up),
            int(down),
            timestamp,
        ).build_transaction({
            'from': account.address,
            'nonce': web3.eth.get_transaction_count(account.address),
            'gasPrice': web3.eth.gas_price,
        })

        try:
            estimated_gas = contract.functions.addTrafficData(
                int(lane),
                int(car),
                int(truck),
                int(total),
                int(up),
                int(down),
                timestamp,
            ).estimate_gas({'from': account.address})
            tx_dict['gas'] = max(int(estimated_gas * 1.25), 120000)
        except Exception as gas_error:
            raise RuntimeError(f"Cannot estimate gas for addTrafficData: {gas_error}") from gas_error

        try:
            contract.functions.addTrafficData(
                int(lane),
                int(car),
                int(truck),
                int(total),
                int(up),
                int(down),
                timestamp,
            ).call({'from': account.address})
        except Exception as call_error:
            raise RuntimeError(f"Preflight call reverted: {call_error}") from call_error

        # Sign and send the transaction
        signed_tx = web3.eth.account.sign_transaction(tx_dict, account.key)
        tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
        receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=180, poll_latency=2)

        if receipt.status != 1:
            raise RuntimeError(
                f"Transaction failed with status {receipt.status}. "
                f"Check CONTRACT_ADDRESS, network, and contract ABI."
            )

        chain_index = None
        try:
            chain_index = int(contract.functions.getTrafficCount().call()) - 1
            if chain_index < 0:
                chain_index = None
        except Exception:
            chain_index = None
        
        print("TX:", tx_hash.hex())
        print("Payload hash:", payload_hash)
        return {
            "tx_hash": tx_hash.hex(),
            "payload_hash": payload_hash,
            "timestamp": timestamp,
            "payload": payload,
            "chain_index": chain_index,
            "block_number": receipt.blockNumber,
        }

    except Exception as e:
        print("Blockchain error:", e)
        return None


def get_traffic_data():
    """Read traffic data from blockchain with retry logic."""
    max_retries = 3
    retry_delay = 0.5  # seconds
    
    for attempt in range(max_retries):
        try:
            count = contract.functions.getTrafficCount().call()
            result = []

            for index in range(count):
                item = contract.functions.trafficList(index).call()
                result.append({
                    "lane": item[0],
                    "car": item[1],
                    "truck": item[2],
                    "total": item[3],
                    "up": item[4],
                    "down": item[5],
                    "timestamp": item[6],
                })

            return result

        except Exception as e:
            if attempt < max_retries - 1:
                print(f"Read error (attempt {attempt + 1}/{max_retries}): {e}")
                time.sleep(retry_delay)
            else:
                print(f"Read error (final attempt): {e}")
                return []


# Test code - try to read data
if __name__ == "__main__":
    print("\n=== TESTING get_traffic_data() ===")
    data = get_traffic_data()
    print(f"Retrieved {len(data)} traffic records")
    for i, record in enumerate(data):
        print(f"  Record {i}: {record}")