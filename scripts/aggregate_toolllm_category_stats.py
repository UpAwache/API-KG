#!/usr/bin/env python3
"""
Aggregate API-KG build statistics from ToolLLM-style category folders.

Reads:  <repo>/sample/out/<Category>_sample_v4/build_report.md
Writes: <paper_workspace>/Ver0.2/generated_stats/
  - category_stats.csv
  - category_scale_summary.tex   (\\input-ready table*)
  - fig_category_scale_overview.pdf
  - fig_category_scale_overview.png
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RE_BOLD_KV = re.compile(r"^-\s*\*\*([^*]+)\*\*:\s*(.+?)\s*$")
RE_EDGE_KV = re.compile(r"^-\s*([a-zA-Z0-9_]+)\s*:\s*(\d+)\s*$")


@dataclass
class CategoryRow:
    category: str
    nodes_total: int
    edges_total: int
    parameter_nodes_canonical: int
    n_tools: int | None
    n_apis: int | None
    depends_on: int | None
    parameter_to_api: int | None
    api_to_parameter: int | None
    source_path: str


def _parse_int(s: str) -> int:
    return int(s.strip().replace(",", ""))


def parse_build_report(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    meta: dict[str, Any] = {}
    edges: dict[str, int] = {}
    mode = "meta"
    for raw in text.splitlines():
        line = raw.rstrip()
        m = RE_BOLD_KV.match(line)
        if m:
            meta[m.group(1).strip()] = m.group(2).strip()
            continue
        if line.strip() == "## edges_by_type":
            mode = "edges"
            continue
        if mode == "edges":
            m2 = RE_EDGE_KV.match(line.strip())
            if m2:
                edges[m2.group(1)] = int(m2.group(2))
    meta["_edges"] = edges
    return meta


def category_from_dir(folder: Path) -> str:
    name = folder.name
    suffix = "_sample_v4"
    if name.endswith(suffix):
        return name[: -len(suffix)]
    return name


def discover_reports(sample_out: Path) -> list[Path]:
    reports: list[Path] = []
    if not sample_out.is_dir():
        return reports
    for child in sorted(sample_out.iterdir()):
        if not child.is_dir() or not child.name.endswith("_sample_v4"):
            continue
        br = child / "build_report.md"
        if br.is_file():
            reports.append(br)
    return reports


def quantiles_inclusive(xs: list[int]) -> tuple[float, float, float]:
    if not xs:
        return (float("nan"), float("nan"), float("nan"))
    ys = sorted(float(x) for x in xs)
    n = len(ys)
    if n == 1:
        v = ys[0]
        return (v, v, v)

    def q_at(p: float) -> float:
        idx = (n - 1) * p
        lo = int(math.floor(idx))
        hi = int(math.ceil(idx))
        if lo == hi:
            return ys[lo]
        w = idx - lo
        return ys[lo] * (1 - w) + ys[hi] * w

    return (q_at(0.25), q_at(0.50), q_at(0.75))


def fmt_num(x: float) -> str:
    if x != x:
        return "---"
    if abs(x - round(x)) < 1e-6:
        v = int(round(x))
        return f"{v:,}".replace(",", "\\,")
    return f"{x:.1f}"


def build_rows(reports: list[Path]) -> list[CategoryRow]:
    rows: list[CategoryRow] = []
    for br in reports:
        meta = parse_build_report(br)
        edges: dict[str, int] = meta.get("_edges", {})
        try:
            nodes_total = _parse_int(str(meta.get("nodes_total", "")))
            edges_total = _parse_int(str(meta.get("edges_total", "")))
            pnc = _parse_int(str(meta.get("parameter_nodes_canonical", "")))
        except Exception:
            print(f"skip (missing ints): {br}", file=sys.stderr)
            continue
        rows.append(
            CategoryRow(
                category=category_from_dir(br.parent),
                nodes_total=nodes_total,
                edges_total=edges_total,
                parameter_nodes_canonical=pnc,
                n_tools=edges.get("category_to_tool"),
                n_apis=edges.get("tool_to_api"),
                depends_on=edges.get("depends_on"),
                parameter_to_api=edges.get("parameter_to_api"),
                api_to_parameter=edges.get("api_to_parameter"),
                source_path=str(br.as_posix()),
            )
        )
    rows.sort(key=lambda r: r.category.lower())
    return rows


def write_csv(rows: list[CategoryRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "category",
        "nodes_total",
        "edges_total",
        "parameter_nodes_canonical",
        "n_tools_category_to_tool",
        "n_apis_tool_to_api",
        "depends_on",
        "parameter_to_api",
        "api_to_parameter",
        "source_path",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "category": r.category,
                    "nodes_total": r.nodes_total,
                    "edges_total": r.edges_total,
                    "parameter_nodes_canonical": r.parameter_nodes_canonical,
                    "n_tools_category_to_tool": r.n_tools if r.n_tools is not None else "",
                    "n_apis_tool_to_api": r.n_apis if r.n_apis is not None else "",
                    "depends_on": r.depends_on if r.depends_on is not None else "",
                    "parameter_to_api": r.parameter_to_api if r.parameter_to_api is not None else "",
                    "api_to_parameter": r.api_to_parameter if r.api_to_parameter is not None else "",
                    "source_path": r.source_path,
                }
            )


def summarize(xs: list[int]) -> tuple[int, float, float, float, int, int]:
    if not xs:
        return (0, float("nan"), float("nan"), float("nan"), 0, 0)
    p25, p50, p75 = quantiles_inclusive(xs)
    return (min(xs), p25, p50, p75, max(xs), sum(xs))


def row_lookup(rows: list[CategoryRow], name: str) -> CategoryRow | None:
    for r in rows:
        if r.category == name:
            return r
    return None


def tex_summary_row(label: str, vals: list[int]) -> str:
    lo, p25, p50, p75, hi, s = summarize(vals)
    # Integer-valued metrics: round quartiles for cleaner tables.
    p25i, p50i, p75i = int(round(p25)), int(round(p50)), int(round(p75))
    cells = [
        fmt_num(float(lo)),
        fmt_num(float(p25i)),
        fmt_num(float(p50i)),
        fmt_num(float(p75i)),
        fmt_num(float(hi)),
        fmt_num(float(s)),
    ]
    return f"    {label} & " + " & ".join(cells) + " \\\\\n"


def spotlight_row(label: str, r: CategoryRow | None) -> str:
    if r is None:
        return f"    {label} & \\multicolumn{{6}}{{c}}{{\\emph{{missing}}}} \\\\\n"
    cells = [
        fmt_num(float(r.nodes_total)),
        fmt_num(float(r.edges_total)),
        fmt_num(float(r.depends_on or 0)),
        fmt_num(float(r.n_apis or 0)),
        fmt_num(float(r.n_tools or 0)),
        fmt_num(float(r.parameter_nodes_canonical)),
    ]
    return f"    {label} & " + " & ".join(cells) + " \\\\\n"


def write_latex_summary(rows: list[CategoryRow], out_tex: Path) -> None:
    n_cats = len(rows)
    nodes = [r.nodes_total for r in rows]
    edges = [r.edges_total for r in rows]
    dep = [r.depends_on or 0 for r in rows]
    apis = [r.n_apis or 0 for r in rows]
    tools = [r.n_tools or 0 for r in rows]
    pnodes = [r.parameter_nodes_canonical for r in rows]

    crypto = row_lookup(rows, "Cryptography")
    food = row_lookup(rows, "Food")

    lines: list[str] = []
    lines.append("% Auto-generated by scripts/aggregate_toolllm_category_stats.py\n")
    lines.append("% Do not edit by hand.\n")
    lines.append("\\begin{table*}[t]\n")
    lines.append("  \\centering\n")
    cap = (
        "  \\caption{ToolLLM-wide API-KG scale summary over $N="
        + str(n_cats)
        + "$ marketplace categories (one \\texttt{build\\_report.md} per category under "
        + "\\texttt{sample/out/*\\_sample\\_v4/}). "
        + "Columns are min / p25 / median / p75 / max / sum across categories; "
        + "per-category CSV: \\texttt{generated\\_stats/category\\_stats.csv}.}"
    )
    lines.append(cap + "\n")
    lines.append("  \\label{tab:toolllm-scale-summary}\n")
    lines.append("  \\small\n")
    lines.append("  \\begin{tabular}{lrrrrrr}\n")
    lines.append("    \\toprule\n")
    lines.append("    Metric & min & p25 & median & p75 & max & sum \\\\\n")
    lines.append("    \\midrule\n")
    lines.append(tex_summary_row("\\#nodes total", nodes))
    lines.append(tex_summary_row("\\#edges total", edges))
    lines.append(tex_summary_row("\\#\\texttt{depends\\_on}", dep))
    lines.append(tex_summary_row("\\#APIs (\\texttt{tool\\_to\\_api})", apis))
    lines.append(tex_summary_row("\\#tools (\\texttt{category\\_to\\_tool})", tools))
    lines.append(tex_summary_row("\\#param.\\ slots (canonical)", pnodes))
    lines.append("    \\midrule\n")
    lines.append("    \\multicolumn{7}{l}{\\textit{Spotlight (same batch):}} \\\\\n")
    lines.append("    \\midrule\n")
    lines.append(
        "    & \\multicolumn{1}{c}{\\textbf{nodes}} & \\multicolumn{1}{c}{\\textbf{edges}} & "
        "\\multicolumn{1}{c}{\\textbf{dep.}} & \\multicolumn{1}{c}{\\textbf{APIs}} & "
        "\\multicolumn{1}{c}{\\textbf{tools}} & \\multicolumn{1}{c}{\\textbf{param.}} \\\\\n"
    )
    lines.append(spotlight_row("\\textsc{Cryptography}", crypto))
    lines.append(spotlight_row("\\textsc{Food}", food))
    lines.append("    \\bottomrule\n")
    lines.append("  \\end{tabular}\n")
    lines.append("\\end{table*}\n")

    out_tex.parent.mkdir(parents=True, exist_ok=True)
    out_tex.write_text("".join(lines), encoding="utf-8")


def write_figure(rows: list[CategoryRow], out_pdf: Path, out_png: Path) -> bool:
    try:
        import matplotlib.pyplot as plt
        from matplotlib import rcParams
    except ImportError:
        print("matplotlib not installed; skip figure", file=sys.stderr)
        return False

    rcParams.update(
        {
            "font.size": 9,
            "axes.labelsize": 10,
            "axes.titlesize": 10,
            "legend.fontsize": 8,
        }
    )

    xs = [max(1, r.nodes_total) for r in rows]
    ys = [max(1, r.edges_total) for r in rows]
    deps = [max(0, r.depends_on or 0) for r in rows]

    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.8), constrained_layout=True)

    ax0 = axes[0]
    sc = ax0.scatter(xs, ys, c=deps, s=28, alpha=0.85, cmap="viridis", edgecolors="none")
    ax0.set_xscale("log")
    ax0.set_yscale("log")
    ax0.set_xlabel("Total nodes (log)")
    ax0.set_ylabel("Total edges (log)")
    ax0.set_title("(a) Category scale scatter")
    cb = fig.colorbar(sc, ax=ax0, shrink=0.75, pad=0.02)
    cb.set_label(r"$\mathit{depends\_on}$")

    # annotate a few extremes
    max_row = max(rows, key=lambda r: r.nodes_total)
    min_row = min(rows, key=lambda r: r.nodes_total)
    for r, off in ((max_row, (6, 6)), (min_row, (6, -10))):
        ax0.annotate(
            r.category.replace("_", " ")[:18],
            (max(1, r.nodes_total), max(1, r.edges_total)),
            textcoords="offset points",
            xytext=off,
            fontsize=7,
            alpha=0.9,
        )

    ax1 = axes[1]
    sorted_nodes = sorted(r.nodes_total for r in rows)
    n = len(sorted_nodes)
    ys_cdf = [(i + 1) / n for i in range(n)]
    ax1.step(sorted_nodes, ys_cdf, where="post", color="#2563eb")
    ax1.set_xscale("log")
    ax1.set_xlabel("Total nodes (log)")
    ax1.set_ylabel("CDF")
    ax1.set_title("(b) Node-count ECDF")
    ax1.set_ylim(0, 1.02)
    ax1.grid(True, which="both", linestyle=":", alpha=0.35)

    fig.suptitle(f"ToolLLM categories (N={n})", fontsize=10, y=1.02)

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_pdf, bbox_inches="tight")
    fig.savefig(out_png, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return True


def find_sample_out(start: Path) -> Path | None:
    """Walk upwards from ``start`` until ``sample/out`` contains category build folders."""
    for d in [start, *start.parents]:
        cand = d / "sample" / "out"
        if not cand.is_dir():
            continue
        if any(p.is_dir() and p.name.endswith("_sample_v4") for p in cand.iterdir()):
            return cand
    return None


def default_paths() -> tuple[Path, Path]:
    """Return (sample_out, ver02_generated) assuming script under ``paper_workspace/scripts/``."""
    script = Path(__file__).resolve()
    paper_workspace = script.parents[1]
    sample_out = find_sample_out(script)
    if sample_out is None:
        sample_out = paper_workspace.parents[3] / "sample" / "out"
    out_dir = paper_workspace / "Ver0.2" / "generated_stats"
    return sample_out, out_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate ToolLLM category build_report stats.")
    parser.add_argument("--sample-out", type=Path, default=None, help="Path to sample/out")
    parser.add_argument("--output-dir", type=Path, default=None, help="Output directory")
    args = parser.parse_args()

    sample_out, out_dir = default_paths()
    if args.sample_out is not None:
        sample_out = args.sample_out
    if args.output_dir is not None:
        out_dir = args.output_dir

    reports = discover_reports(sample_out)
    if not reports:
        print(f"No build_report.md found under: {sample_out}", file=sys.stderr)
        return 1

    rows = build_rows(reports)
    csv_path = out_dir / "category_stats.csv"
    tex_path = out_dir / "category_scale_summary.tex"
    pdf_path = out_dir / "fig_category_scale_overview.pdf"
    png_path = out_dir / "fig_category_scale_overview.png"

    write_csv(rows, csv_path)
    write_latex_summary(rows, tex_path)
    ok_fig = write_figure(rows, pdf_path, png_path)

    print(f"Wrote {csv_path} ({len(rows)} rows)")
    print(f"Wrote {tex_path}")
    if ok_fig:
        print(f"Wrote {pdf_path} and {png_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
