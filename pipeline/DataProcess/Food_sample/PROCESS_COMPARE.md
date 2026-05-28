# Food_sample 数据处理分步对比

## 0. 本次流程
- 数据源复制：`00_source_copy/tools_Food`（来自 `tools/Food`）
- 基线复制：`00_source_copy/kg_baseline`（来自 `out/Food_sample`，若存在）
- 清洗结果：`01_cleaned/cleaned_tools.jsonl` + `cleaning_report.md`
- 语义补全结果：`02_semantic_completion/semantic_completed_tools.jsonl` + `semantic_completion_report.md`
- 预处理结果：`03_preprocessed/parameters_enriched.jsonl` + `normalization_map.json` + `preprocess_report.md`

## 1. 阶段 A（原 API 数据清洗）
- JSON 文件数：`138`
- 可用 Tool 数：`138`
- API 数：`561`
- 输入参数数：required `659` + optional `471`
- 输出样本参数数：`322`（受 body 覆盖率影响）

## 2. 阶段 B（SemanticCompletion 语义补全）
- 输入参数语义补全数：`1130`
- 输出参数语义补全数：`322`
- 输出全 generic_slot 的 API 数：`0`

### semantic enrichment 计数（前 12）
- input_semantic_description: 1130
- output_semantic_description: 322

## 3. 阶段 C（语义解释 + 归一化）
- 参数行（输入+输出）：`1452`
- 规范参数 ID 去重后：`936`
- 低置信度待复核：`0`

### 置信度分布
- high: 1452

### Top 语义角色（前 12）
- recipe_id: 42
- bigoven_username: 40
- api_key: 39
- page_number: 33
- bigoven_password: 24
- order_uid: 20
- pagination_offset: 20
- user_password: 18
- page_size: 18
- max_result_count: 18
- max_results_count: 11
- user_id: 10

## 4. 阶段 D（v4 跨工具依赖 KG 重建）
- v4 节点总数：`1512`
- v4 边总数：`2264`
- v4 归一化 Parameter 节点数：`812`
- v4 depends_on：`113`
- v4 输出目录：`DataProcess/out/Food_sample_v4/`（保留历史版本供对比）

## 5. 你关心的“参数传递与一致性”目前落地情况
- 已把参数从“仅名字+类型”提升为“语义角色 + 规范参数ID + 置信度”。
- `review_queue.jsonl` 已单列低置信度项，可人工修订后再回写规则。
- 已基于 `canonical_param_id` 重建 Parameter 节点与 depends_on（阶段 C 已落地）。
- 下一步建议：人工抽查低置信度与 depends_on 误连，再微调角色规则。
