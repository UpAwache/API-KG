# Cryptography_sample 数据处理分步对比

## 0. 本次流程
- 数据源复制：`00_source_copy/tools_Cryptography`（来自 `tools/Cryptography`）
- 基线复制：`00_source_copy/kg_baseline`（来自 `out/Cryptography_sample`，若存在）
- 清洗结果：`01_cleaned/cleaned_tools.jsonl` + `cleaning_report.md`
- 语义补全结果：`02_semantic_completion/semantic_completed_tools.jsonl` + `semantic_completion_report.md`
- 预处理结果：`03_preprocessed/parameters_enriched.jsonl` + `normalization_map.json` + `preprocess_report.md`

## 1. 阶段 A（原 API 数据清洗）
- JSON 文件数：`20`
- 可用 Tool 数：`20`
- API 数：`84`
- 输入参数数：required `39` + optional `36`
- 输出样本参数数：`14`（受 body 覆盖率影响）

## 2. 阶段 B（SemanticCompletion 语义补全）
- 输入参数语义补全数：`75`
- 输出参数语义补全数：`14`
- 输出全 generic_slot 的 API 数：`0`

### semantic enrichment 计数（前 12）
- input_semantic_description: 75
- output_semantic_description: 14

## 3. 阶段 C（语义解释 + 归一化）
- 参数行（输入+输出）：`89`
- 规范参数 ID 去重后：`42`
- 低置信度待复核：`0`

### 置信度分布
- high: 89

### Top 语义角色（前 12）
- crypto_key: 16
- stark_key: 7
- address: 6
- json_payload: 5
- data_payload: 4
- message_text: 4
- contract_address: 4
- project_uuid: 4
- chain: 3
- limit: 3
- asset_id: 3
- page_cursor: 2

## 4. 阶段 D（v4 跨工具依赖 KG 重建）
- v4 节点总数：`140`
- v4 边总数：`207`
- v4 归一化 Parameter 节点数：`35`
- v4 depends_on：`14`
- v4 输出目录：`DataProcess/out/Cryptography_sample_v4/`（保留历史版本供对比）

## 5. 你关心的“参数传递与一致性”目前落地情况
- 已把参数从“仅名字+类型”提升为“语义角色 + 规范参数ID + 置信度”。
- `review_queue.jsonl` 已单列低置信度项，可人工修订后再回写规则。
- 已基于 `canonical_param_id` 重建 Parameter 节点与 depends_on（阶段 C 已落地）。
- 下一步建议：人工抽查低置信度与 depends_on 误连，再微调角色规则。
