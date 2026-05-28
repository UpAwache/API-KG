# API-KG

Static API knowledge graph resource built from ToolBench-style JSON catalogs (CIKM resource paper draft).

## Repository contents

| Path | Description |
|------|-------------|
| `generated_stats/category_stats.csv` | Machine-readable per-category counts for **50** ToolLLM marketplace partitions (batch build under `*_sample_v4`). |

## ToolLLM category scale (N = 50)

Counts from one `build_report.md` per marketplace category. **Nodes** / **Edges** are graph totals; **Tools** = `category_to_tool` edges; **APIs** = `tool_to_api` edges; **Dep.** = `depends_on` edges (semantic-key default).

| Category | Nodes | Edges | Tools | APIs | Dep. | Param. slots |
|----------|------:|------:|------:|-----:|-----:|-------------:|
| Advertising | 1,169 | 2,443 | 158 | 641 | 279 | 369 |
| Artificial Intelligence Machine Learning | 1,677 | 3,077 | 390 | 990 | 580 | 296 |
| Business | 4,519 | 16,636 | 695 | 2,148 | 8,922 | 1,675 |
| Business Software | 5,874 | 49,609 | 350 | 3,550 | 32,679 | 1,973 |
| Commerce | 1,499 | 5,789 | 214 | 811 | 2,846 | 473 |
| Communication | 2,259 | 7,565 | 252 | 1,173 | 3,089 | 833 |
| Cryptography | 140 | 207 | 20 | 84 | 14 | 35 |
| Customized | 3 | 2 | 1 | 1 | — | 0 |
| Cybersecurity | 176 | 233 | 28 | 90 | 10 | 57 |
| Data | 7,734 | 76,005 | 831 | 3,583 | 59,195 | 3,319 |
| Database | 1,633 | 3,976 | 277 | 900 | 1,653 | 455 |
| Devices | 469 | 728 | 38 | 287 | 87 | 143 |
| eCommerce | 3,893 | 290,880 | 441 | 2,037 | 278,839 | 1,414 |
| Education | 1,780 | 4,797 | 294 | 925 | 1,860 | 560 |
| Email | 1,858 | 7,682 | 161 | 1,140 | 3,420 | 556 |
| Energy | 462 | 1,280 | 32 | 198 | 342 | 231 |
| Entertainment | 2,711 | 17,101 | 411 | 1,421 | 11,933 | 878 |
| Events | 767 | 1,958 | 35 | 461 | 200 | 270 |
| Finance | 6,503 | 58,252 | 559 | 3,834 | 44,419 | 2,109 |
| Financial | 2,145 | 20,288 | 215 | 1,136 | 15,333 | 793 |
| Food | 1,229 | 2,798 | 138 | 561 | 647 | 529 |
| Gaming | 2,293 | 8,195 | 248 | 1,253 | 3,935 | 791 |
| Health and Fitness | 816 | 1,458 | 93 | 449 | 142 | 273 |
| Jobs | 92 | 227 | 15 | 47 | 74 | 29 |
| Location | 1,638 | 9,849 | 281 | 724 | 6,460 | 632 |
| Logistics | 675 | 1,123 | 63 | 279 | 29 | 332 |
| Mapping | 860 | 2,530 | 100 | 344 | 822 | 415 |
| Media | 1,707 | 7,470 | 194 | 916 | 3,437 | 596 |
| Medical | 451 | 736 | 60 | 241 | 91 | 149 |
| Monitoring | 517 | 859 | 66 | 301 | 122 | 149 |
| Movies | 505 | 1,654 | 63 | 227 | 625 | 214 |
| Music | 1,680 | 7,338 | 152 | 1,030 | 3,423 | 497 |
| News Media | 1,141 | 2,626 | 133 | 676 | — | 331 |
| Other | 2,949 | 12,651 | 363 | 1,806 | 5,834 | 779 |
| Payments | 779 | 1,759 | 48 | 368 | 95 | 362 |
| Reward | 42 | 43 | 6 | 28 | — | 7 |
| Science | 585 | 1,076 | 64 | 272 | 134 | 248 |
| Search | 1,057 | 3,374 | 162 | 402 | 1,317 | 492 |
| SMS | 675 | 1,852 | 86 | 315 | 606 | 273 |
| Social | 4,101 | 74,425 | 348 | 2,392 | 64,252 | 1,360 |
| Sports | 6,211 | 34,421 | 361 | 4,455 | 17,639 | 1,394 |
| Storage | 1,155 | 3,140 | 33 | 754 | 144 | 367 |
| Text Analysis | 2,026 | 5,253 | 466 | 1,129 | 1,801 | 430 |
| Tools | 3,800 | 11,440 | 704 | 1,916 | 5,372 | 1,179 |
| Translation | 609 | 1,911 | 114 | 305 | 873 | 189 |
| Transportation | 1,156 | 2,428 | 84 | 573 | 112 | 498 |
| Travel | 1,772 | 5,046 | 154 | 724 | 1,475 | 893 |
| Video Images | 1,935 | 4,379 | 280 | 986 | — | 668 |
| Visual Recognition | 1,193 | 2,284 | 270 | 649 | 259 | 273 |
| Weather | 824 | 2,979 | 106 | 405 | 1,092 | 312 |

**Batch totals:** 91,744 nodes, 783,832 edges across 50 categories.

Paper spotlight: **Jobs** (92 nodes, 227 edges) — **Data** (7,734 nodes, 76,005 edges).

## Paper

Draft: *API-KG: A Static API Knowledge Graph Resource from Real-World API Ecosystems*.

## License

TBD — align with ToolBench / RapidAPI third-party terms before public artifact release.

## Extended artifact layout (this sync)

| Path | Description |
|------|-------------|
| `pipeline/` | Static KG build code (`DataProcess/run_pipeline.py`, `build_static_kg.py`, …). |
| `source_data/<Category>/00_source_copy/` | Per-category ToolBench JSON snapshots used as build input. |
| `graphs/out/<Category>_sample_v4/` | Built `nodes.jsonl`, `edges.jsonl`, `build_report.md`, and `viz/kg_interactive.html` when <100MB. |
| `scripts/aggregate_toolllm_category_stats.py` | Regenerate `generated_stats/category_stats.csv` from `graphs/out`. |
| `OMITTED_LARGE_FILES.txt` | Blobs skipped (GitHub 100MB hard limit); regenerate with `pipeline/visualize_kg.py`. |

### Visualization

Interactive HTML is included for **all 51** `*_sample_v4` categories. **eCommerce** `viz/kg_interactive.html` (~169MB) is stored via **Git LFS** (see `.gitattributes`); clone with `git lfs pull` to fetch the full file.

### Large source JSON

A few raw ToolBench JSON files in `source_data/` also exceed 100MB; see `OMITTED_LARGE_FILES.txt`.

### Reproduce stats

```bash
python scripts/aggregate_toolllm_category_stats.py \
  --graphs-root graphs/out \
  --out-dir generated_stats
```
