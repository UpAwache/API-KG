# DataProcess 流程说明（Cryptography_sample）

> 本文用于解释 `static_kg/DataProcess` 下每个步骤在做什么，以及每一步的典型处理例子。

---

## 一、目录与步骤对应关系

- `00_source_copy/`：复制原始输入与 baseline 输出（保证可回溯、可对比）
- `01_cleaned/`：原 API 数据清洗（Raw Cleaning）
- `02_semantic_completion/`：语义补全（SemanticCompletion）
- `03_preprocessed/`：参数归一化与预处理（Normalization + Preprocess）
- `../out/Cryptography_sample_v4/`：当前重建的 v4 KG（不覆盖原版；历史 `v3` 目录可保留对比）

---

## 二、核心处理链路（Step 00 ~ Step 03）

### Step 00：数据源复制（Source Copy）

### 作用
- 固定本次实验输入快照，避免后续源数据变化影响可复现性。
- 把原始 KG baseline 一起放进来，后面可以直接做 v1 vs v2 对比。

### 典型例子
1. **复制原始 API json**
   - 从 `tools/Cryptography/*.json` 复制到 `00_source_copy/tools_Cryptography/`。
   - 例如 `fanfury.json`、`cryptocurrency_news.json`、`securityapi.json` 都被保留原样。

2. **复制 baseline KG**
   - 从 `static_kg/out/Cryptography_sample/` 复制 `nodes.jsonl`、`edges.jsonl`、`build_report.md`、`schema_notes.json` 到 `00_source_copy/kg_baseline/`。

3. **对比前后有参照物**
   - 后续如果你看到 v2 的 depends_on 变少/变多，可以直接回看 baseline 边数量与结构。

---

### Step 01：清洗（01_cleaned）

### 作用
- 把原始 JSON 的结构先标准化，减少脏数据对后续语义判断和归一化的干扰。

### 典型处理例子
1. **方法与路径标准化**
   - `method` 统一大写（如 `get` -> `GET`）。
   - URL 提取成 `path_key`（如 `GET:/v1/coindesk`），用于后续定位 API 上下文。

2. **参数名规范化**
   - 例如 `messageName` 会得到 `name_norm=messagename`，`user_addr` 保留规范形式。
   - 后续匹配、合并时不受大小写和符号细节影响。

3. **输出样本提取（受限版）**
   - 从可用 body 中抽 `output_keys_sample`（如新闻 API 的 `key1`、`key2`）。
   - 若 body 不可用/过大/非 dict，则跳过，避免引入噪声。

---

### Step 02：语义补全（02_semantic_completion）

### 作用
- 在“归一化”之前，先给每个参数补上**语义描述信息**（`semantic_description`）。
- 这一步只做“加信息”，不做“合并参数”。
- 当前实现已接入千问 API 生成一句话语义描述；若未配置 API Key 或请求失败，会使用本地兜底描述，保证流程可运行。

### 典型处理例子
1. **给输入参数补描述**
   - 例如把 `asset_id` 补成：
   - `asset_id 是接口 Get Asset Detail（GET:/asset/detail）的输入参数，类型为 STRING，用于表达资产对象标识。`
   - 注意这里是“描述增强”，不是“标签归并”。

2. **给输出参数补描述**
   - 对 `output_keys_sample` 也补同样格式描述，保证输入/输出在同一语义框架下可比较。
   - 若可用字段不足，则保留最小描述并标记 `output_semantic_needs_review`。

3. **未来接入 LLM 的提示词（草案）**
   - 输入：`param_name`、`param_desc`、`api_name`、`path`、`io_kind`、`value_type`
   - 输出：一段自然语言语义描述 + 一个可归一化的 `fine_role` 候选（不输出 coarse 类别）

### 一个完全具体的例子（同一参数在 Step 02 被依次添加的信息）

以参数 `asset_id` 为例（假设它来自某个 API 的 required 参数）：

1. **清洗后已有基础字段（Step 01 产物）**
   - `name = "asset_id"`
   - `name_norm = "asset_id"`
   - `value_type = "STRING"`
   - `description = "The unique identifier of the asset"`

2. **进入 Step 02 时，补充上下文字段（来自当前 API）**
   - `api_name = "Get Asset Detail"`（示例）
   - `path_key = "GET:/asset/detail"`（示例）
   - `io_kind = "input_required"`

3. **生成并写入语义描述（新增字段）**
   - 新增：`semantic_description`
   - 典型内容（示例，一句话）：
   - `asset_id 表示资产对象的唯一标识符，用于在 Get Asset Detail 接口中定位目标资产。`

4. **记录语义来源（新增字段）**
   - 新增：`semantic_source = "name_desc_context"`

5. **如需人工复核时的标记（可选）**
   - 对输出参数场景，若描述中无法形成有效 `fine_role`，会在 API 级别标 `output_semantic_needs_review = true`
   - 该 `asset_id` 输入参数通常不会触发这条

---

### Step 03：预处理与归一化（03_preprocessed）

### 作用
- 把 Step 02 生成的“富语义描述”压缩成“规范参数 ID（canonical_param_id）”。
- 在这一步才做“把多的信息搞少”，实现跨 API 参数去重与统一。

### 典型处理例子
1. **生成 canonical_param_id**
   - 新格式：`<TYPE>:<fine_role>:<tool_domain>`。
   - 例如：
     - `STRING:asset_id:reddio_nft_token_and_ipfs`
     - `STRING:order_id:reddio_nft_token_and_ipfs`
     - `STRING:wallet_address:crypto_whale_tracker`

2. **低置信度分流**
   - 从 `semantic_description` 抽不到明确 `fine_role` 的参数，会进入低置信度队列。
   - 输出到 `review_queue.jsonl`，方便人工专项检查。

3. **映射可追溯**
   - `normalization_map.json` 记录 “原参数 -> 规范参数” 的映射关系。
   - 便于定位“为什么这个参数被归到这个 canonical”。

---

## 三、全流程串联与产物重建（Step 04）

### 作用
- 把 Step 00~03 的产物串成一条完整流水线，形成可直接检查与对比的最终图谱结果。
- 用归一化后的参数重建 KG，当前样例输出到 `DataProcess/out/Cryptography_sample_v4/`，不覆盖原始图（可与 `v3` 对比）。

### 典型处理例子
1. **Parameter 节点全局合并（按语义，不按工具）**
   - 图中参数节点 ID 为 `parameter_norm:<TYPE>:<fine_role>`：同一类型且同一 `fine_role` 只保留一个节点，不同工具/API 的同名语义边都连到它。
   - Step 03 里的 `canonical_param_id` 仍可带 `tool_domain`，用于追溯映射；图上展示以全局节点为准。

2. **依赖边（跨工具）**
   - `depends_on` 在输出与输入的 `match_key`（即 `<TYPE>:<fine_role>`）有交集时添加，允许跨工具、跨品类。

3. **可视化双开对比**
   - 新结果：`DataProcess/out/Cryptography_sample_v4/viz/*.html`
   - 原结果：`static_kg/out/Cryptography_sample/viz/*.html`
   - 可以直接双开看参数星团、依赖链变化。

---

## 四、你现在最该盯的两个点

1. **`generic_slot` 的拆分质量**
   - 如果太多，会导致语义不清晰；
   - 如果拆得过细，可能降低跨 API 可连接性。

2. **输出参数语义覆盖**
   - 当前输出语义仍受 body 质量限制；
   - 下一轮可增强 schema/body 深层解析，提高输出语义可靠度。

---

## 五、一句话总结

这套 DataProcess 流程的本质是：
**先把数据洗干净，再把参数“讲明白”，最后再用规范语义去重建图。**

你后续做方法改进时，建议始终先在这个局部样例上跑一遍，再推广到全量。
