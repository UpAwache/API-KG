# 静态 API-KG 构建（单品类）

```bash
python build_static_kg.py --category Reward
```

- 默认读取仓库根目录下的 `tools/`（可用 `--tools-root` 覆盖）。
- 输出默认在 `static_kg/out/<Category>/`（可用 `--out-dir` 覆盖）。

工作说明与结果解读见：`WEEK6_STATIC_KG_PROGRESS.md`。

## 交互式可视化（HTML）

脚本与样式均在 **`static_kg/viz/`**；依赖：`pip install -r viz/requirements-viz.txt`（在 `static_kg` 目录下执行时路径为 `viz/requirements-viz.txt`）。

**推荐改样式流程**：编辑人类可读的 **`viz/viz_style.md`**（文末 `yaml` 代码块），然后：

```bash
cd static_kg
pip install -r viz/requirements-viz.txt
python viz/sync_viz_style.py          # md 中的 YAML -> viz_style.json
python viz/visualize_kg.py            # 读 json 出 HTML
# 或一步：python viz/visualize_kg.py --sync-md
```

- 默认读取 `out/Reward/`，生成 **`out/Reward/viz/kg_interactive.html`**。
- `--overview` 时默认 **`out/Reward/viz/kg_overview.html`**。
- `--kg-dir`：品类根目录（含 `nodes.jsonl`，不要指到 `viz/`）。
- `--output`：可显式指定任意 HTML 路径。
- 样式：默认 **`viz/viz_style.json`**；可用 `python viz/visualize_kg.py --config 其它.json`。若手写/工具改过 JSON，可用 **`python viz/sync_viz_style.py --from-json`** 把 JSON 写回 `viz_style.md` 里的 YAML 块（说明文字保留）。

用浏览器打开生成的 HTML 即可（拖拽、滚轮缩放、悬停看属性）；需能访问 CDN。

若 JSON 只写部分字段，会与程序内置默认值合并。
