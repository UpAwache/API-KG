"""
Static API-KG builder for a single `tools/<Category>/` subtree (Outline §3.3).
BUILD_RULES_VERSION: bump when matching / ID rules change.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

BUILD_RULES_VERSION = "v0.1"
MAX_BODY_JSON_CHARS = 50_000
MAX_BODY_TOP_KEYS = 40


def norm_param_name(name: str) -> str:
    s = (name or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_") or "unnamed"


def norm_param_type(t: str) -> str:
    return (t or "STRING").strip().upper() or "STRING"


def api_path_key(url: str, method: str) -> str:
    p = urlparse(url)
    path = (p.path or "/").rstrip("/") or "/"
    return f"{method.upper()}:{path}"


def stable_api_id(host: str, url: str, method: str, index: int) -> str:
    host = (host or "").strip().lower()
    key = api_path_key(url, method)
    raw = f"{host}|{key}|{index}"
    h = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"api:{host}:{h}"


def tool_id(category: str, stem: str) -> str:
    return f"tool:{category}:{stem}"


def category_id(category: str) -> str:
    return f"category:{category}"


def parameter_slot_id(value_type: str, logical_name: str) -> str:
    return f"parameter:{norm_param_type(value_type)}:{norm_param_name(logical_name)}"


def output_parameter_id(api_id: str, key: str) -> str:
    return f"parameter:OUT:{api_id}:{norm_param_name(key)}"


def types_compatible(out_t: str, in_t: str) -> bool:
    a, b = norm_param_type(out_t), norm_param_type(in_t)
    if a == b:
        return True
    if a == "STRING" or b == "STRING":
        return True
    return False


def names_compatible(out_name: str, in_name: str) -> tuple[bool, float]:
    o, i = norm_param_name(out_name), norm_param_name(in_name)
    if not o or not i:
        return False, 0.0
    if o == i:
        return True, 1.0
    if o in i or i in o:
        return True, 0.75
    # token overlap
    ot, it = set(o.split("_")), set(i.split("_"))
    ot.discard("")
    it.discard("")
    if ot and it and (ot & it):
        return True, 0.55
    return False, 0.0


def infer_json_type(v: Any) -> str:
    if v is None:
        return "STRING"
    if isinstance(v, bool):
        return "BOOLEAN"
    if isinstance(v, int) and not isinstance(v, bool):
        return "NUMBER"
    if isinstance(v, float):
        return "NUMBER"
    if isinstance(v, str):
        return "STRING"
    if isinstance(v, list):
        return "ARRAY"
    if isinstance(v, dict):
        return "OBJECT"
    return "STRING"


def shallow_body_outputs(ep: dict[str, Any]) -> list[tuple[str, str]]:
    body = ep.get("body")
    if body is None:
        return []
    try:
        s = json.dumps(body, ensure_ascii=False)
    except (TypeError, ValueError):
        return []
    if len(s) > MAX_BODY_JSON_CHARS:
        return []
    if not isinstance(body, dict):
        return []
    out: list[tuple[str, str]] = []
    for k, v in list(body.items())[:MAX_BODY_TOP_KEYS]:
        if not isinstance(k, str):
            continue
        out.append((k, infer_json_type(v)))
    return out


@dataclass
class APIRecord:
    api_id: str
    tool_id: str
    host: str
    name: str
    method: str
    url: str
    index: int
    inputs: list[tuple[str, str, str]] = field(default_factory=list)
    outputs: list[tuple[str, str, str]] = field(default_factory=list)


def load_tool_json(path: Path, category: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[skip json] {path}: {e}")
        return None


def build_for_category(tools_root: Path, category: str, out_dir: Path) -> None:
    cat_path = tools_root / category
    if not cat_path.is_dir():
        raise SystemExit(f"Category dir not found: {cat_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    nodes.append(
        {
            "id": category_id(category),
            "node_type": "category",
            "label": category,
        }
    )

    apis: list[APIRecord] = []
    skipped_parse = 0
    total_files = 0

    for jpath in sorted(cat_path.rglob("*.json")):
        if not jpath.is_file():
            continue
        total_files += 1
        rel = jpath.relative_to(cat_path)
        stem = jpath.stem
        data = load_tool_json(jpath, category)
        if data is None:
            skipped_parse += 1
            continue
        api_list = data.get("api_list")
        if not api_list or not isinstance(api_list, list):
            skipped_parse += 1
            continue

        tid = tool_id(category, stem)
        tool_name = data.get("tool_name") or data.get("name") or stem
        host = data.get("host") or ""
        nodes.append(
            {
                "id": tid,
                "node_type": "tool",
                "tool_name": tool_name,
                "host": host,
                "source_relpath": str(Path(category) / rel).replace("\\", "/"),
                "home_url": data.get("home_url"),
                "pricing": data.get("pricing"),
                "score": data.get("score"),
            }
        )
        edges.append({"edge_type": "category_to_tool", "src": category_id(category), "dst": tid})

        for idx, ep in enumerate(api_list):
            if not isinstance(ep, dict):
                continue
            method = (ep.get("method") or "GET").upper()
            url = ep.get("url") or ""
            name = ep.get("name") or f"endpoint_{idx}"
            aid = stable_api_id(host, url, method, idx)
            nodes.append(
                {
                    "id": aid,
                    "node_type": "api",
                    "name": name,
                    "method": method,
                    "url": url,
                    "path_key": api_path_key(url, method),
                    "tool_id": tid,
                    "index_in_tool": idx,
                }
            )
            edges.append({"edge_type": "tool_to_api", "src": tid, "dst": aid})

            rec = APIRecord(
                api_id=aid,
                tool_id=tid,
                host=host,
                name=name,
                method=method,
                url=url,
                index=idx,
            )

            for sec, role in (("required_parameters", "required"), ("optional_parameters", "optional")):
                for p in ep.get(sec) or []:
                    if not isinstance(p, dict):
                        continue
                    pn = p.get("name") or ""
                    pt = norm_param_type(p.get("type"))
                    pid = parameter_slot_id(pt, pn)
                    rec.inputs.append((pid, pn, pt))
                    if not any(n["id"] == pid for n in nodes if n.get("node_type") == "parameter"):
                        nodes.append(
                            {
                                "id": pid,
                                "node_type": "parameter",
                                "param_name": pn,
                                "value_type": pt,
                                "slot_kind": "input_shape",
                            }
                        )
                    edges.append(
                        {
                            "edge_type": "parameter_to_api",
                            "role": role,
                            "src": pid,
                            "dst": aid,
                        }
                    )

            for key, vt in shallow_body_outputs(ep):
                pid = output_parameter_id(aid, key)
                rec.outputs.append((pid, key, vt))
                if not any(n["id"] == pid for n in nodes):
                    nodes.append(
                        {
                            "id": pid,
                            "node_type": "parameter",
                            "param_name": key,
                            "value_type": vt,
                            "slot_kind": "output_sample",
                            "source_api": aid,
                        }
                    )
                edges.append({"edge_type": "api_to_parameter", "src": aid, "dst": pid})

            apis.append(rec)

    tool_by_api = {a.api_id: a.tool_id for a in apis}
    tool_score: dict[str, dict | None] = {}
    for n in nodes:
        if n.get("node_type") == "tool":
            tool_score[n["id"]] = n.get("score")

    def edge_cost_prior(src_api: str, dst_api: str) -> float:
        t1, t2 = tool_by_api.get(src_api), tool_by_api.get(dst_api)
        lat = []
        for t in (t1, t2):
            sc = tool_score.get(t) if t else None
            if isinstance(sc, dict) and sc.get("avgLatency") is not None:
                try:
                    lat.append(float(sc["avgLatency"]))
                except (TypeError, ValueError):
                    pass
        base = max(lat) / 1000.0 if lat else 0.5
        return round(base + 0.15, 4)

    def success_prior(api_a: str, api_b: str) -> float:
        t1, t2 = tool_by_api.get(api_a), tool_by_api.get(api_b)
        rates = []
        for t in (t1, t2):
            sc = tool_score.get(t) if t else None
            if isinstance(sc, dict) and sc.get("avgSuccessRate") is not None:
                try:
                    rates.append(float(sc["avgSuccessRate"]) / 100.0)
                except (TypeError, ValueError):
                    pass
        if not rates:
            return 0.5
        return round(sum(rates) / len(rates), 4)

    depends_candidates: list[dict[str, Any]] = []
    for a in apis:
        for b in apis:
            if a.api_id == b.api_id:
                continue
            best: tuple[float, str, str, str, str] | None = None
            for _pid_a, name_a, type_a in a.outputs:
                for _pid_b, name_b, type_b in b.inputs:
                    if not types_compatible(type_a, type_b):
                        continue
                    ok, conf = names_compatible(name_a, name_b)
                    if not ok or conf < 0.5:
                        continue
                    if best is None or conf > best[0]:
                        best = (conf, a.api_id, b.api_id, name_a, name_b)
            if best:
                conf, src_id, dst_id, oname, iname = (
                    best[0],
                    best[1],
                    best[2],
                    best[3],
                    best[4],
                )
                sig = f"out:{oname}~>in:{iname}"
                depends_candidates.append(
                    {
                        "edge_type": "depends_on",
                        "src": src_id,
                        "dst": dst_id,
                        "mapping_signature": sig,
                        "match_confidence": round(conf, 3),
                        "est_cost": edge_cost_prior(src_id, dst_id),
                        "success_freq_prior": success_prior(src_id, dst_id),
                    }
                )

    seen_pairs: set[tuple[str, str]] = set()
    for d in depends_candidates:
        key = (d["src"], d["dst"])
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        edges.append(d)

    inputs_hash_parts: list[str] = []
    for jpath in sorted(cat_path.rglob("*.json")):
        if jpath.is_file():
            rel = jpath.relative_to(tools_root)
            try:
                sz = jpath.stat().st_size
            except OSError:
                sz = -1
            inputs_hash_parts.append(f"{rel.as_posix()}\t{sz}")
    input_fingerprint = hashlib.sha256("\n".join(inputs_hash_parts).encode()).hexdigest()[:20]

    def write_jsonl(path: Path, rows: list[dict]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    write_jsonl(out_dir / "nodes.jsonl", nodes)
    write_jsonl(out_dir / "edges.jsonl", edges)

    n_cat = sum(1 for n in nodes if n["node_type"] == "category")
    n_tool = sum(1 for n in nodes if n["node_type"] == "tool")
    n_api = sum(1 for n in nodes if n["node_type"] == "api")
    n_param = sum(1 for n in nodes if n["node_type"] == "parameter")
    n_dep = sum(1 for e in edges if e["edge_type"] == "depends_on")
    apis_with_out = sum(1 for a in apis if a.outputs)
    apis_total = len(apis)

    report = f"""# Build report ({category})

- **BUILD_RULES_VERSION**: `{BUILD_RULES_VERSION}`
- **input_fingerprint** (paths + sizes under tools root): `{input_fingerprint}`
- **tools_root**: `{tools_root}`
- **category**: `{category}`
- **json_files_seen**: {total_files}
- **parse_or_empty_skips**: {skipped_parse}
- **nodes**: category={n_cat}, tool={n_tool}, api={n_api}, parameter={n_param}, **total**={len(nodes)}
- **edges_by_type**:
"""
    ec = defaultdict(int)
    for e in edges:
        ec[e["edge_type"]] += 1
    for k in sorted(ec):
        report += f"  - {k}: {ec[k]}\n"
    report += f"- **depends_on_edges**: {n_dep}\n"
    report += f"- **apis_with_output_params** (from body): {apis_with_out} / {apis_total}\n"
    report += f"- **MAX_BODY_JSON_CHARS**: {MAX_BODY_JSON_CHARS}\n"

    (out_dir / "build_report.md").write_text(report, encoding="utf-8")

    schema = {
        "BUILD_RULES_VERSION": BUILD_RULES_VERSION,
        "node_types": ["category", "tool", "api", "parameter"],
        "edge_types": [
            "category_to_tool",
            "tool_to_api",
            "parameter_to_api",
            "api_to_parameter",
            "depends_on",
        ],
        "id_conventions": {
            "category": "category:<CategoryFolderName>",
            "tool": "tool:<Category>:<json_stem_without_extension>",
            "api": "api:<host>:<sha256_16>( host|METHOD:path|index )",
            "parameter_input": "parameter:<TYPE>:<normalized_name>",
            "parameter_output": "parameter:OUT:<api_id>:<normalized_key>",
        },
        "depends_on_rule": "Output parameter (from sampled body top-level keys) matches input parameter by compatible types and name similarity >= 0.5; one edge per ordered API pair first match.",
    }
    (out_dir / "schema_notes.json").write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_dir / 'nodes.jsonl'} ({len(nodes)} nodes)")
    print(f"Wrote {out_dir / 'edges.jsonl'} ({len(edges)} edges)")
    print(f"Wrote {out_dir / 'build_report.md'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--tools-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "tools",
        help="Path to ToolBench `tools` directory",
    )
    ap.add_argument("--category", default="Reward", help="Single first-level category folder name")
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory (default: static_kg/out/<category>)",
    )
    args = ap.parse_args()
    out = args.out_dir or (Path(__file__).resolve().parent / "out" / args.category)
    build_for_category(args.tools_root.resolve(), args.category, out.resolve())


if __name__ == "__main__":
    main()
