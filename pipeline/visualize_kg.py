"""
Render static API-KG (nodes.jsonl + edges.jsonl) as an interactive HTML graph (pyvis).

Styles are read from `viz_style.json` (or `--config`). Edit that file to tune
colors, sizes, shapes, fonts, edge widths, and physics.

Usage:
  pip install -r static_kg/requirements-viz.txt
  python static_kg/visualize_kg.py --kg-dir static_kg/out/Reward
  python static_kg/visualize_kg.py --config my_style.json
"""

from __future__ import annotations

import argparse
import copy
import html
import json
import re
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


# 当 viz_style.json 缺字段或损坏时的兜底（与仓库内 viz_style.json 保持语义一致）
DEFAULT_VIZ_STYLE: dict[str, Any] = {
    "canvas": {
        "height_px": 920,
        "background_color": "#0f172a",
        "default_font_color": "#e2e8f0",
    },
    "nodes": {
        "_default": {
            "color": "#475569",
            "border_color": "#94a3b8",
            "border_width": 2,
            "highlight_background": None,
            "highlight_border": "#f8fafc",
            "size": 16,
            "shape": "dot",
            "font_size": 12,
            "font_color": None,
            "shadow": True,
            "label_max_chars": 36,
        },
        "category": {
            "color": "#7c3aed",
            "border_color": "#ddd6fe",
            "border_width": 3,
            "size": 34,
            "shape": "box",
            "font_size": 16,
            "label_max_chars": 20,
        },
        "tool": {
            "color": "#2563eb",
            "border_color": "#93c5fd",
            "border_width": 3,
            "size": 28,
            "shape": "ellipse",
            "font_size": 14,
            "label_max_chars": 42,
        },
        "api": {
            "color": "#0e7490",
            "border_color": "#22d3ee",
            "border_width": 3,
            "size": 24,
            "shape": "hexagon",
            "font_size": 12,
            "label_max_chars": 54,
        },
        "parameter": {
            "color": "#475569",
            "border_color": "#64748b",
            "border_width": 1,
            "size": 9,
            "shape": "dot",
            "font_size": 9,
            "label_max_chars": 30,
        },
    },
    "edges": {
        "_default": {
            "color": "#64748b",
            "width": 1.2,
            "dashes": False,
            "highlight": "#f8fafc",
        },
        "category_to_tool": {"color": "#a78bfa", "width": 2},
        "tool_to_api": {"color": "#60a5fa", "width": 2},
        "parameter_to_api": {"color": "#94a3b8", "width": 1.2, "dashes": True},
        "api_to_parameter": {"color": "#2dd4bf", "width": 1.2, "dashes": True},
        "depends_on": {"color": "#ea580c", "width": 4},
    },
    "physics": {
        "full": {
            "enabled": True,
            "solver": "forceAtlas2Based",
            "forceAtlas2Based": {
                "gravitationalConstant": -42,
                "centralGravity": 0.006,
                "springLength": 150,
                "springConstant": 0.038,
                "damping": 0.55,
                "avoidOverlap": 0.65,
            },
            "stabilization": {"iterations": 240},
        },
        "overview": {
            "enabled": True,
            "solver": "repulsion",
            "repulsion": {
                "nodeDistance": 200,
                "centralGravity": 0.12,
                "springLength": 220,
            },
            "stabilization": {"iterations": 200},
        },
    },
}


def _deep_merge_defaults(default: Any, user: Any) -> Any:
    if isinstance(user, dict) and isinstance(default, dict):
        out = copy.deepcopy(default)
        for k, v in user.items():
            if isinstance(k, str) and k.startswith("_"):
                continue
            if k in out and isinstance(out[k], dict) and isinstance(v, dict):
                out[k] = _deep_merge_defaults(out[k], v)
            else:
                out[k] = copy.deepcopy(v)
        return out
    return copy.deepcopy(user) if user is not None else copy.deepcopy(default)


def load_viz_style(config_path: Path) -> dict[str, Any]:
    base = copy.deepcopy(DEFAULT_VIZ_STYLE)
    if not config_path.is_file():
        return base
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise SystemExit(f"无法读取样式配置 {config_path}: {e}") from e
    return _deep_merge_defaults(base, raw)


def _resolve_node_style(style: dict[str, Any], node_type: str) -> dict[str, Any]:
    nodes = style.get("nodes") or {}
    out = copy.deepcopy(nodes.get("_default") or {})
    spec = nodes.get(node_type, {})
    for k, v in spec.items():
        if isinstance(k, str) and k.startswith("_"):
            continue
        out[k] = v
    return out


def _resolve_edge_style(style: dict[str, Any], edge_type: str) -> dict[str, Any]:
    edges = style.get("edges") or {}
    out = copy.deepcopy(edges.get("_default") or {})
    spec = edges.get(edge_type, {})
    for k, v in spec.items():
        if isinstance(k, str) and k.startswith("_"):
            continue
        out[k] = v
    return out


def _vis_node_color(st: dict[str, Any], canvas: dict[str, Any]) -> dict[str, Any]:
    bg = st["color"]
    bor = st.get("border_color") or "#ffffff"
    hi_bg = st.get("highlight_background") or bg
    hi_bo = st.get("highlight_border") or "#f8fafc"
    return {
        "background": bg,
        "border": bor,
        "highlight": {"background": hi_bg, "border": hi_bo},
    }


def _short(s: str, n: int = 36) -> str:
    s = (s or "").replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def node_label(n: dict[str, Any], st: dict[str, Any]) -> str:
    t = n.get("node_type") or ""
    lim = int(st.get("label_max_chars") or 36)
    if t == "category":
        return _short(n.get("label") or n.get("id", ""), lim)
    if t == "tool":
        return _short(n.get("tool_name") or n["id"].split(":")[-1], lim)
    if t == "api":
        name = n.get("name") or ""
        pk = n.get("path_key") or ""
        return _short(f"{name}\n{pk}", lim)
    if t == "parameter":
        pn = n.get("param_name") or ""
        vt = n.get("value_type") or ""
        return _short(f"{pn} [{vt}]", lim)
    return _short(n.get("id", ""), lim)


def node_title(n: dict[str, Any]) -> str:
    lines: list[str] = [
        f"<b>{html.escape(str(n.get('id', '')))}</b>",
        f"type: {html.escape(str(n.get('node_type', '')))}",
    ]
    skip = {"id", "node_type"}
    for k, v in sorted(n.items()):
        if k in skip or v is None:
            continue
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)[:500]
        lines.append(f"{k}: {html.escape(str(v)[:800])}")
    return "<br/>".join(lines)


def edge_title(e: dict[str, Any]) -> str:
    parts = [f"<b>{html.escape(str(e.get('edge_type', '')))}</b>"]
    for k in ("role", "mapping_signature", "match_confidence", "est_cost", "success_freq_prior"):
        if k in e and e[k] is not None:
            parts.append(f"{k}: {html.escape(str(e[k]))}")
    parts.append(f"{html.escape(str(e.get('src', '')))} → {html.escape(str(e.get('dst', '')))}")
    return "<br/>".join(parts)


def filter_for_overview(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    keep_types = {"category", "tool", "api"}
    node_ids = {n["id"] for n in nodes if n.get("node_type") in keep_types}
    new_nodes = [n for n in nodes if n["id"] in node_ids]
    new_edges = [
        e
        for e in edges
        if e.get("edge_type") in ("category_to_tool", "tool_to_api", "depends_on")
        and e.get("src") in node_ids
        and e.get("dst") in node_ids
    ]
    return new_nodes, new_edges


def _legend_html(title: str, *, overview: bool, style: dict[str, Any]) -> str:
    canvas = style.get("canvas") or {}
    node_legend: list[tuple[str, str]] = [
        ("Category", _resolve_node_style(style, "category")["color"]),
        ("Tool", _resolve_node_style(style, "tool")["color"]),
        ("API", _resolve_node_style(style, "api")["color"]),
    ]
    if not overview:
        node_legend.append(("Parameter", _resolve_node_style(style, "parameter")["color"]))
    node_rows = "".join(
        f'<div class="lg-row"><span class="sw" style="background:{c}"></span>{html.escape(n)}</div>'
        for n, c in node_legend
    )
    edge_items: list[tuple[str, str]] = [
        ("category → tool", _resolve_edge_style(style, "category_to_tool")["color"]),
        ("tool → api", _resolve_edge_style(style, "tool_to_api")["color"]),
    ]
    if not overview:
        edge_items.extend(
            [
                ("parameter ⇢ api (虚线)", _resolve_edge_style(style, "parameter_to_api")["color"]),
                ("api ⇢ parameter (虚线)", _resolve_edge_style(style, "api_to_parameter")["color"]),
            ]
        )
    edge_items.append(("depends_on", _resolve_edge_style(style, "depends_on")["color"]))
    edge_rows = "".join(
        f'<div class="lg-row"><span class="ln" style="background:{c}"></span>{html.escape(l)}</div>'
        for l, c in edge_items
    )
    cfg_hint = html.escape(str(style.get("_config_path", "viz_style.json")))
    mode = "结构总览（无 Parameter）" if overview else "完整（含 Parameter）"
    return f"""
<div id="kg-legend">
  <div class="lg-title">{html.escape(title)}</div>
  <div class="lg-sub">{html.escape(mode)} · 样式: {cfg_hint}</div>
  <div class="lg-section">节点</div>
  {node_rows}
  <div class="lg-section">边</div>
  {edge_rows}
</div>
<style>
#kg-legend {{
  position: fixed; top: 10px; left: 10px; z-index: 9;
  font: 13px/1.4 system-ui, Segoe UI, sans-serif;
  color: {html.escape(str(canvas.get("default_font_color", "#e2e8f0")))};
  background: rgba(15,23,42,.92);
  border: 1px solid #334155; border-radius: 8px; padding: 10px 12px;
  max-width: 280px; box-shadow: 0 4px 20px rgba(0,0,0,.35);
}}
#kg-legend .lg-title {{ font-weight: 700; font-size: 14px; margin-bottom: 2px; }}
#kg-legend .lg-sub {{ font-size: 11px; color: #94a3b8; margin-bottom: 8px; }}
#kg-legend .lg-section {{ font-size: 11px; text-transform: uppercase; letter-spacing: .06em;
  color: #94a3b8; margin: 8px 0 4px; }}
#kg-legend .lg-row {{ display: flex; align-items: center; gap: 8px; margin: 3px 0; }}
#kg-legend .sw {{ width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0;
  border: 1px solid rgba(255,255,255,.25); }}
#kg-legend .ln {{ width: 18px; height: 3px; border-radius: 1px; flex-shrink: 0; }}
</style>
"""


def _strip_pyvis_duplicate_heading_blocks(text: str) -> str:
    """Remove pyvis template's two identical <center><h1>…</h1></center> blocks (same {{heading}} twice)."""
    pattern = r"<center>\s*<h1>.*?</h1>\s*</center>\s*"
    text, _ = re.subn(pattern, "", text, count=2, flags=re.DOTALL)
    return text


def _inject_legend(html_path: Path, legend_fragment: str) -> None:
    raw = html_path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    text = _strip_pyvis_duplicate_heading_blocks(text)
    text = text.replace(
        '<script src="lib/bindings/utils.js"></script>',
        "<!-- pyvis local utils omitted; not required for vis-network drawGraph -->\n",
    )
    needle = '<div id="mynetwork"'
    if needle not in text:
        return
    if "kg-legend" in text:
        html_path.write_text(text, encoding="utf-8", newline="\n")
        return
    text, n = re.subn(r"(<body[^>]*>)", r"\1\n" + legend_fragment + "\n", text, count=1)
    if n == 0:
        return
    html_path.write_text(text, encoding="utf-8", newline="\n")


def build_html(
    kg_dir: Path,
    out_path: Path,
    *,
    overview: bool,
    style: dict[str, Any],
) -> None:
    try:
        from pyvis.network import Network
    except ImportError as exc:
        raise SystemExit(
            "需要安装 pyvis: pip install -r static_kg/requirements-viz.txt\n" f"详情: {exc}"
        ) from exc

    nodes_path = kg_dir / "nodes.jsonl"
    edges_path = kg_dir / "edges.jsonl"
    if not nodes_path.is_file() or not edges_path.is_file():
        raise SystemExit(f"未找到 {nodes_path} 或 {edges_path}，请先运行 build_static_kg.py")

    nodes = load_jsonl(nodes_path)
    edges = load_jsonl(edges_path)
    title_cat = kg_dir.name
    for n in nodes:
        if n.get("node_type") == "category" and n.get("label"):
            title_cat = str(n["label"])
            break

    if overview:
        nodes, edges = filter_for_overview(nodes, edges)

    canvas = style.get("canvas") or {}
    h = int(canvas.get("height_px") or 920)
    bg = str(canvas.get("background_color") or "#0f172a")
    fg = str(canvas.get("default_font_color") or "#e2e8f0")

    # heading 不设：pyvis 默认模板会把 {{heading}} 渲染两次，图例里已有 lg-title
    net = Network(
        height=f"{h}px",
        width="100%",
        directed=True,
        bgcolor=bg,
        font_color=fg,
        heading="",
        cdn_resources="remote",
    )

    for n in nodes:
        nid = n["id"]
        nt = n.get("node_type") or "unknown"
        st = _resolve_node_style(style, nt)
        fc = st.get("font_color") or fg
        net.add_node(
            nid,
            label=node_label(n, st),
            title=node_title(n),
            color=_vis_node_color(st, canvas),
            size=int(st.get("size") or 16),
            shape=str(st.get("shape") or "dot"),
            borderWidth=int(st.get("border_width") or 2),
            font={"size": int(st.get("font_size") or 12), "color": fc},
            shadow=bool(st.get("shadow", True)),
        )

    for e in edges:
        et = e.get("edge_type") or ""
        est = _resolve_edge_style(style, et)
        ec = str(est.get("color") or "#64748b")
        ew = float(est.get("width") or 1.2)
        dashes = bool(est.get("dashes", False))
        hi = str(est.get("highlight") or "#f8fafc")
        edge_kw: dict[str, Any] = {
            "title": edge_title(e),
            "color": {"color": ec, "highlight": hi},
            "width": ew,
            "arrows": "to",
        }
        if dashes:
            edge_kw["dashes"] = True
        net.add_edge(e["src"], e["dst"], **edge_kw)

    phys_key = "overview" if overview else "full"
    physics = copy.deepcopy((style.get("physics") or {}).get(phys_key) or DEFAULT_VIZ_STYLE["physics"][phys_key])

    opts: dict[str, Any] = {
        "nodes": {"shadow": True},
        "edges": {"smooth": {"type": "continuous"}},
        "physics": physics,
        "interaction": {"hover": True, "tooltipDelay": 120, "multiselect": True, "navigationButtons": True},
    }
    net.set_options(json.dumps(opts))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    net.write_html(str(out_path))
    style_for_legend = dict(style)
    style_for_legend["_config_path"] = style.get("_config_path", "viz_style.json")
    _inject_legend(out_path, _legend_html(f"API-KG · {title_cat}", overview=overview, style=style_for_legend))


def main() -> None:
    ap = argparse.ArgumentParser(description="Visualize API-KG from nodes.jsonl / edges.jsonl")
    default_kg = Path(__file__).resolve().parent / "out" / "Reward"
    default_cfg = Path(__file__).resolve().parent / "viz_style.json"
    ap.add_argument(
        "--kg-dir",
        type=Path,
        default=default_kg,
        help="Directory containing nodes.jsonl and edges.jsonl",
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output HTML path (default: <kg-dir>/kg_interactive.html)",
    )
    ap.add_argument(
        "--overview",
        action="store_true",
        help="Only category / tool / api nodes and structural + depends_on edges (hide parameters)",
    )
    ap.add_argument(
        "--config",
        type=Path,
        default=default_cfg,
        help="JSON style file (see viz_style.json for schema)",
    )
    args = ap.parse_args()
    kg_dir = args.kg_dir.resolve()
    cfg_path = args.config.resolve()
    viz_style = load_viz_style(cfg_path)
    viz_style["_config_path"] = cfg_path.name if cfg_path.is_file() else "viz_style.json (内置默认)"

    out = args.output or (kg_dir / "kg_interactive.html")
    build_html(kg_dir, out, overview=args.overview, style=viz_style)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()

