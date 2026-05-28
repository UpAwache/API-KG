# SemanticCompletion 具体样例（不是数字，是真实参数）

> 数据来源：`semantic_completed_tools.jsonl`。  
> 目标：让你直观看到“这个参数为什么被补全成这个语义角色”。

---

## 1) 补全规则简述（本次）

- 输入参数：基于 `参数名 + 参数描述 + API 名称 + path_key` 进行语义判定。
- 输出参数：基于 `输出键名 + API 名称 + path_key` 进行语义判定。
- 证据不足时回退 `generic_slot`。

---

## 2) 代表性输入参数样例

### A. `address`

1. 参数 `user_addr`（`STRING`）  
   - API：`Address history`（`GET:/history/list`）  
   - Tool：`₿ Crypto Whale Tracker 🚀`  
   - 补全：`semantic_role_hint = address`（`name_desc_context`）

2. 参数 `addr`（`STRING`）  
   - API：`Address info`（`GET:/user/addr`）  
   - Tool：`₿ Crypto Whale Tracker 🚀`  
   - 补全：`semantic_role_hint = address`（`name_desc_context`）

3. 参数 `contract_address`（`STRING`）  
   - API：`GetAssetsbycontractinformation`（`GET:/v1/assetid`）  
   - Tool：`Reddio NFT, Token and IPFS`  
   - 描述包含 “Contract address...”  
   - 补全：`semantic_role_hint = address`

---

### B. `identifier`

1. 参数 `asset_id`（`STRING`）  
   - API：`GetAssetsdetailbyassetid`（`GET:/v1/assetid/{asset_id}`）  
   - Tool：`Reddio NFT, Token and IPFS`  
   - 描述：`The asset id you want to retrieve information`  
   - 补全：`semantic_role_hint = identifier`

2. 参数 `order_id`（`STRING`）  
   - API：`GetOrderbyOrderID`（`GET:/v1/order`）  
   - Tool：`Reddio NFT, Token and IPFS`  
   - 描述：`the order id you want to query`  
   - 补全：`semantic_role_hint = identifier`

3. 参数 `project_uuid`（`STRING`）  
   - API：`GetMarketplaces`（`GET:/v1/project/.../marketplace`）  
   - Tool：`Reddio NFT, Token and IPFS`  
   - 补全：`semantic_role_hint = identifier`

---

### C. `file_blob`

1. 参数 `file`（`BINARY`）  
   - API：`UploadDocument`（`POST:/api/v1/documents`）  
   - Tool：`hexsign`  
   - 补全：`semantic_role_hint = file_blob`

2. 参数 `image`（`BINARY`）  
   - API：`Bind and crypt a message to an image`（`POST:/messinimage/`）  
   - Tool：`No Intrusive steganografy`  
   - 描述：`The image`  
   - 补全：`semantic_role_hint = file_blob`

3. 参数 `image`（`BINARY`）  
   - API：`Get the message binded to an image`（`POST:/getmess/`）  
   - Tool：`No Intrusive steganografy`  
   - 描述：`The image containing the message`  
   - 补全：`semantic_role_hint = file_blob`

---

### D. `cipher_text`

1. 参数 `data`（`STRING`）  
   - API：`base64 encrypt`（`GET:/base64/encrypt/{data}`）  
   - Tool：`securityAPI`  
   - 补全：`semantic_role_hint = cipher_text`

2. 参数 `json`（`STRING`）  
   - API：`decrypt with aes`（`GET:/aes/decrypt/{json}`）  
   - Tool：`securityAPI`  
   - 补全：`semantic_role_hint = cipher_text`

3. 参数 `json`（`STRING`）  
   - API：`encrypt with aes`（`GET:/aes/encrypt/{json}`）  
   - Tool：`securityAPI`  
   - 补全：`semantic_role_hint = cipher_text`

---

### E. `crypto_key_material`

1. 参数 `stark_key`（`STRING`）  
   - API：`GetRecordsbystark_key`（`GET:/v1/records`）  
   - Tool：`Reddio NFT, Token and IPFS`  
   - 补全：`semantic_role_hint = crypto_key_material`

2. 参数 `s` / `r`（`STRING`）  
   - API：`Getrecordbysignature`（`GET:/v1/record/by/signature`）  
   - Tool：`Reddio NFT, Token and IPFS`  
   - 描述包含 signature  
   - 补全：`semantic_role_hint = crypto_key_material`

3. 参数 `format`（`STRING`）  
   - API：`get rsa keys`（`GET:/rsa/key/{format}`）  
   - Tool：`securityAPI`  
   - 补全：`semantic_role_hint = crypto_key_material`

---

### F. `generic_slot`（证据不足的兜底）

1. 参数 `order_by`（`STRING`）  
   - API：`Whale portfolios`（`GET:/whale/list`）  
   - Tool：`₿ Crypto Whale Tracker 🚀`  
   - 补全：`semantic_role_hint = generic_slot`

2. 参数 `limit`（`STRING`）  
   - API：`Trade signals`（`GET:/activity/list`）  
   - Tool：`₿ Crypto Whale Tracker 🚀`  
   - 补全：`semantic_role_hint = generic_slot`

3. 参数 `json`（`STRING`）  
   - API：`password checker`（`GET:/pass/{json}`）  
   - Tool：`securityAPI`  
   - 补全：`semantic_role_hint = generic_slot`

4. 参数 `contract1`（`STRING`）  
   - API：`GetOrderInfo`（`GET:/v1/order/info`）  
   - Tool：`Reddio NFT, Token and IPFS`  
   - 补全：`semantic_role_hint = generic_slot`

---

## 3) 代表性输出参数样例

### 输出 `key1` / `key2` -> `crypto_key_material`

来自以下 API（均在 `Cryptocurrency News` Tool）：
- `CoinDesk`（`GET:/v1/coindesk`）
- `Bitcoinist`（`GET:/v1/bitcoinist`）
- `Cointelegraph`（`GET:/v1/cointelegraph`）
- `The Guardian`（`GET:/v1/theguardian`）
- `BSC News`（`GET:/v1/bsc`）
- `Decrypt`（`GET:/v1/decrypt`）

以及 `securityAPI` 的：
- `encrypt with aes`（`GET:/aes/encrypt/{json}`）的输出 `key1`、`key2`

这些输出键名本身语义偏弱（`key1/key2`），当前按“key+上下文”归到了 `crypto_key_material`；后续仍建议用更深层 schema/body 或文档语义做二次细化。

---

## 4) 一句话结论

这轮 SemanticCompletion 已经把多数参数从“纯字符串名字”升级为可解释语义；  
但 `generic_slot` 和 `key1/key2` 仍是下一轮精修重点（尤其要防止误并/误连）。

