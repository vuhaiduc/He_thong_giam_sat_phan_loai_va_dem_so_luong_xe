# Cấu hình Ethereum (Thay thế Ganache)

Dự án đã được cập nhật để sử dụng Ethereum thực tế thay vì Ganache local.

## Tùy chọn kết nối RPC

### 1. **Sử dụng Public RPC (Miễn phí, nhưng chậm)**
- Không cần cấu hình, mặc định sử dụng: `https://eth.llamarpc.com`
- Phù hợp để đọc dữ liệu (read-only), không khuyến nghị cho gửi transaction

### 2. **Sử dụng Infura**
```bash
# Lấy API key từ https://infura.io/
export INFURA_API_KEY="your_infura_api_key"
```

### 3. **Sử dụng Alchemy**
```bash
# Lấy API key từ https://www.alchemy.com/
export ALCHEMY_API_KEY="your_alchemy_api_key"
```

### 4. **Sử dụng Custom RPC URL**
```bash
export ETH_RPC_URL="https://your-rpc-endpoint.com"
```

### 5. **Contract Address**
```bash
export CONTRACT_ADDRESS="0xYourDeployedContractAddress"
```

## Gửi Transaction lên Ethereum

Để gửi transaction lên mainnet, bạn cần:

1. **Private Key**: Xuất khóa riêng tư
```bash
export PRIVATE_KEY="your_private_key_hex"
```

2. **ETH trong ví**: Để trả gas fees

3. **Contract Address**: Thiết lập `CONTRACT_ADDRESS` đúng với contract đã deploy trên cùng network với RPC

## Ví dụ thiết lập trên Windows

```powershell
# Thêm vào PowerShell profile hoặc set tạm thời
$env:INFURA_API_KEY = "your_key"
$env:PRIVATE_KEY = "your_private_key"

# Chạy ứng dụng
python app.py
```

## Ví dụ thiết lập trên Linux/Mac

```bash
export INFURA_API_KEY="your_key"
export PRIVATE_KEY="your_private_key"

python app.py
```

## Lưu ý quan trọng

⚠️ **Bảo mật**:
- Không hardcode private key trong code
- Không share private key với ai
- Sử dụng environment variables

⚠️ **Chi phí**:
- Mỗi transaction trên mainnet tốn ETH (gas fees)
- Kiểm tra giá gas trước khi gửi

⚠️ **Test Network**:
- Nếu muốn test không tốn tiền, sử dụng Sepolia testnet:
```bash
export ETH_RPC_URL="https://sepolia.infura.io/v3/YOUR_INFURA_KEY"
```

## Cấu trúc các hàm

### `send_traffic_data()`
- Gửi dữ liệu giao thông lên blockchain
- Cần contract address, ABI, và account hợp lệ
- Trả về transaction hash

### `get_traffic_data()`
- Đọc dữ liệu từ blockchain (không cần private key)
- Hoạt động trên bất kỳ RPC endpoint nào
