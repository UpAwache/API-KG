from __future__ import annotations

import json
import argparse
import re
import shutil
import hashlib
import os
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

MAX_BODY_JSON_CHARS = 50_000
QWEN_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
QWEN_MODEL = os.environ.get("QWEN_MODEL", "qwen-plus")
_SEMANTIC_DESC_CACHE: dict[str, str] = {}
_FINE_ROLE_CACHE: dict[str, str] = {}
_PIPELINE_PROGRESS_LOG: Path | None = None


def set_pipeline_progress_log(path: Path | None) -> None:
    """设置进度快照文件路径；供 Agent 运行时你在编辑器里打开该文件即可看到进度。"""
    global _PIPELINE_PROGRESS_LOG
    _PIPELINE_PROGRESS_LOG = path.resolve() if path is not None else None


def _format_duration_sec(sec: float) -> str:
    """将秒数格式化为简短可读字符串（含 ETA）。"""
    if sec < 0:
        return "0s"
    if sec < 60:
        return f"{sec:.0f}s"
    m = int(sec // 60)
    s = int(sec % 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h = m // 60
    m = m % 60
    return f"{h}h{m:02d}m"


def _write_progress_snapshot(desc: str, current: int, total: int, t0_monotonic: float | None = None) -> None:
    """将当前进度写入文本文件（多行，便于非 TTY 环境查看）；可选根据阶段起始时间估算 ETA。"""
    if _PIPELINE_PROGRESS_LOG is None or total <= 0:
        return
    pct = 100.0 * min(current, total) / total
    lines = [
        f"updated_at: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"stage: {desc}",
        f"current: {current}",
        f"total: {total}",
        f"percent: {pct:.2f}",
    ]
    if t0_monotonic is not None:
        elapsed = max(time.monotonic() - t0_monotonic, 1e-6)
        lines.append(f"elapsed_sec: {elapsed:.1f}")
        if current > 0:
            rate = min(current, total) / elapsed
            lines.append(f"rate_param_per_sec: {rate:.3f}")
            rem = max(0, total - min(current, total))
            if rem <= 0:
                lines.append("eta_sec_remaining: 0")
                lines.append("eta_human: 0s")
            elif rate > 0:
                eta_sec = rem / rate
                lines.append(f"eta_sec_remaining: {eta_sec:.1f}")
                lines.append(f"eta_human: {_format_duration_sec(eta_sec)} (estimate)")
            else:
                lines.append("eta_sec_remaining: (unknown)")
                lines.append("eta_human: (unknown)")
        else:
            lines.append("rate_param_per_sec: (waiting for first item)")
            lines.append("eta_sec_remaining: (unknown)")
            lines.append("eta_human: (unknown)")
    lines.append("")
    text = "\n".join(lines)
    path = _PIPELINE_PROGRESS_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    # Windows：目标文件若被编辑器独占打开，os.replace 会失败；直接 write 通常仍可更新。
    try:
        path.write_text(text, encoding="utf-8", newline="\n")
    except OSError:
        alt = path.with_name(path.stem + ".live" + path.suffix)
        alt.write_text(text, encoding="utf-8", newline="\n")


def _count_semantic_completion_params(tools: list[dict[str, Any]]) -> int:
    """统计阶段 02 需生成语义描述的参数条数（输入+输出样本）。"""
    n = 0
    for t in tools:
        for api in t.get("apis", []):
            n += len(api.get("required_parameters") or [])
            n += len(api.get("optional_parameters") or [])
            n += len(api.get("output_keys_sample") or [])
    return n


def _count_preprocess_param_rows(tools: list[dict[str, Any]]) -> int:
    """统计阶段 03 enriched 行数（与遍历结构一致）。"""
    return _count_semantic_completion_params(tools)


def _progress_bar(total: int, desc: str) -> Any:
    """
    进度条：已安装 tqdm 时用真正的 bar；否则用控制台百分比回退。
    若已 set_pipeline_progress_log()，每次 update 会刷新进度快照文件（便于 Agent 运行时查看）。
    返回对象需支持 .update(n=1) 与 .close()。
    """
    total = max(0, int(total))
    if total == 0:

        class _Noop:
            def update(self, n: int = 1) -> None:
                pass

            def close(self) -> None:
                pass

        return _Noop()

    class _TeeBar:
        def __init__(self, inner: Any, tot: int, d: str) -> None:
            self._inner = inner
            self._tot = tot
            self._d = d
            self._n = 0
            self._t0 = time.monotonic()

        def update(self, n: int = 1) -> None:
            self._n += n
            _write_progress_snapshot(self._d, min(self._n, self._tot), self._tot, self._t0)
            self._inner.update(n)

        def close(self) -> None:
            self._inner.close()
            if _PIPELINE_PROGRESS_LOG is not None:
                _write_progress_snapshot(f"{self._d} (done)", self._tot, self._tot, self._t0)

    try:
        from tqdm import tqdm

        return _TeeBar(tqdm(total=total, desc=desc, unit="param", dynamic_ncols=True), total, desc)
    except ImportError:

        class _Fallback:
            def __init__(self, tot: int, d: str) -> None:
                self._tot = tot
                self._n = 0
                self._d = d
                self._t0 = time.monotonic()

            def update(self, n: int = 1) -> None:
                self._n += n
                climit = min(self._n, self._tot)
                _write_progress_snapshot(self._d, climit, self._tot, self._t0)
                pct = 100.0 * climit / self._tot
                print(f"\r{self._d}: {climit}/{self._tot} ({pct:.1f}%)", end="", flush=True)

            def close(self) -> None:
                print()
                if _PIPELINE_PROGRESS_LOG is not None:
                    _write_progress_snapshot(f"{self._d} (done)", self._tot, self._tot, self._t0)

        return _Fallback(total, desc)


def norm_name(name: str) -> str:
    """工具函数：统一参数名格式（小写+下划线）；阶段 01/02/03 公共依赖。"""
    s = (name or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_") or "unnamed"


def norm_type(t: str) -> str:
    """工具函数：统一参数类型为大写；阶段 01/02/03 公共依赖。"""
    return ((t or "STRING").strip().upper()) or "STRING"


def infer_role(name: str, desc: str, api_name: str, path_key: str) -> tuple[str, str]:
    """遗留规则函数：基于关键词推断粗粒度语义与置信度（当前主流程基本不依赖）。"""
    text = f"{name} {desc} {api_name} {path_key}".lower()
    n = norm_name(name)
    if any(k in text for k in ["addr", "address", "wallet"]):
        return "address", "high"
    if any(k in text for k in ["cipher", "encrypt", "decrypt"]):
        return "cipher_text", "medium"
    if "key" in n:
        if any(k in text for k in ["aes", "rsa", "hmac", "crypto", "signature"]):
            return "crypto_key_material", "medium"
        return "kv_or_identifier_key", "low"
    if any(k in n for k in ["id", "uuid", "identifier", "token_id", "asset_id", "order_id"]):
        return "identifier", "high"
    if any(k in text for k in ["file", "image", "blob", "upload"]):
        return "file_blob", "high"
    if any(k in n for k in ["start", "end", "time", "date", "timestamp"]):
        return "time_range", "medium"
    if any(k in n for k in ["text", "message", "content", "data"]):
        return "content_text", "medium"
    return "generic_slot", "low"


def canonical_id(value_type: str, fine_role: str, domain: str) -> str:
    """阶段 03：生成规范参数 ID（<TYPE>:<fine_role>:<tool_domain>）。"""
    return f"{norm_type(value_type)}:{fine_role}:{domain}"


def global_parameter_node_id(value_type: str, fine_role: str) -> str:
    """阶段 04：全局参数节点 ID，仅按 TYPE+fine_role 合并，不区分工具/品类。"""
    return f"parameter_norm:{norm_type(value_type)}:{fine_role}"


def api_path_key(url: str, method: str) -> str:
    """工具函数：将 URL+METHOD 规范化为 path_key；阶段 01/04 使用。"""
    p = urlparse(url or "")
    path = (p.path or "/").rstrip("/") or "/"
    return f"{(method or 'GET').upper()}:{path}"


def stable_api_id(host: str, url: str, method: str, index: int) -> str:
    """阶段 04：生成稳定 API 节点 ID（host+path_key+index 哈希）。"""
    host = (host or "").strip().lower()
    raw = f"{host}|{api_path_key(url, method)}|{index}"
    h = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"api:{host}:{h}"


def load_json(path: Path) -> Any:
    """工具函数：读取 JSON 文件（UTF-8，容错解码）。"""
    with open(path, encoding="utf-8", errors="replace") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    """工具函数：写入 JSON 文件（UTF-8，带缩进）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """工具函数：写入 JSONL 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def copy_source(tools_category_dir: Path, baseline_out_dir: Path, target_root: Path, category: str) -> None:
    """阶段 00：复制原始 tools 与 baseline KG，固定实验输入快照。"""
    raw_tools_dir = target_root / "00_source_copy" / f"tools_{category}"
    baseline_dir = target_root / "00_source_copy" / "kg_baseline"
    raw_tools_dir.mkdir(parents=True, exist_ok=True)
    baseline_dir.mkdir(parents=True, exist_ok=True)

    for src in sorted(tools_category_dir.glob("*.json")):
        shutil.copy2(src, raw_tools_dir / src.name)

    for name in ["nodes.jsonl", "edges.jsonl", "build_report.md", "schema_notes.json", "schema_notes_v4.json"]:
        src = baseline_out_dir / name
        if src.exists():
            shutil.copy2(src, baseline_dir / name)


def stage_clean(raw_tools_dir: Path, out_dir: Path) -> dict[str, Any]:
    """阶段 01：清洗原始 API JSON，产出结构化 cleaned_tools 与清洗报告。"""
    cleaned_rows: list[dict[str, Any]] = []
    stats = Counter()
    missing = Counter()
    sample_issues: list[str] = []

    for p in sorted(raw_tools_dir.glob("*.json")):
        stats["json_seen"] += 1
        try:
            obj = load_json(p)
        except Exception:
            stats["json_parse_fail"] += 1
            sample_issues.append(f"parse_fail: {p.name}")
            continue

        api_list = obj.get("api_list")
        if not isinstance(api_list, list) or len(api_list) == 0:
            stats["empty_api_list"] += 1
            sample_issues.append(f"empty_api_list: {p.name}")
            continue

        tool_row: dict[str, Any] = {
            "source_file": p.name,
            "tool_name": (obj.get("tool_name") or obj.get("name") or p.stem).strip(),
            "host": (obj.get("host") or "").strip().lower(),
            "home_url": obj.get("home_url"),
            "pricing": obj.get("pricing"),
            "score": obj.get("score"),
            "apis": [],
        }

        for idx, api in enumerate(api_list):
            if not isinstance(api, dict):
                continue
            method = ((api.get("method") or "GET").strip().upper()) or "GET"
            url = (api.get("url") or "").strip()
            name = (api.get("name") or f"endpoint_{idx}").strip()
            if not url:
                missing["api.url"] += 1
            if not name:
                missing["api.name"] += 1
            path_key = re.sub(r"^https?://[^/]+", "", url).strip() or "/"
            api_row: dict[str, Any] = {
                "index_in_tool": idx,
                "name": name,
                "method": method,
                "url": url,
                "path_key": f"{method}:{path_key}",
                "required_parameters": [],
                "optional_parameters": [],
                "output_keys_sample": [],
            }

            for sec in ["required_parameters", "optional_parameters"]:
                role = "required" if sec == "required_parameters" else "optional"
                plist = api.get(sec) or []
                if not isinstance(plist, list):
                    plist = []
                for prm in plist:
                    if not isinstance(prm, dict):
                        continue
                    raw_name = (prm.get("name") or "").strip()
                    if not raw_name:
                        missing[f"{role}.name"] += 1
                        continue
                    raw_type = norm_type(prm.get("type"))
                    api_row[sec].append(
                        {
                            "name": raw_name,
                            "name_norm": norm_name(raw_name),
                            "value_type": raw_type,
                            "description": (prm.get("description") or "").strip() or None,
                        }
                    )

            body = api.get("body")
            if body is not None:
                try:
                    body_str = json.dumps(body, ensure_ascii=False)
                    if len(body_str) <= MAX_BODY_JSON_CHARS and isinstance(body, dict):
                        for k, v in list(body.items())[:40]:
                            if isinstance(k, str):
                                vt = "STRING"
                                if isinstance(v, bool):
                                    vt = "BOOLEAN"
                                elif isinstance(v, (int, float)):
                                    vt = "NUMBER"
                                elif isinstance(v, list):
                                    vt = "ARRAY"
                                elif isinstance(v, dict):
                                    vt = "OBJECT"
                                api_row["output_keys_sample"].append(
                                    {"name": k, "name_norm": norm_name(k), "value_type": vt}
                                )
                    else:
                        stats["body_skipped_too_large_or_nondict"] += 1
                except Exception:
                    stats["body_serialize_fail"] += 1

            tool_row["apis"].append(api_row)
            stats["api_total"] += 1
            stats["required_param_total"] += len(api_row["required_parameters"])
            stats["optional_param_total"] += len(api_row["optional_parameters"])
            stats["output_param_total"] += len(api_row["output_keys_sample"])

        cleaned_rows.append(tool_row)
        stats["tool_total"] += 1

    write_jsonl(out_dir / "cleaned_tools.jsonl", cleaned_rows)
    rep_lines = [
        "# Cleaning Report",
        "",
        f"- json_seen: {stats['json_seen']}",
        f"- json_parse_fail: {stats['json_parse_fail']}",
        f"- empty_api_list: {stats['empty_api_list']}",
        f"- tool_total: {stats['tool_total']}",
        f"- api_total: {stats['api_total']}",
        f"- required_param_total: {stats['required_param_total']}",
        f"- optional_param_total: {stats['optional_param_total']}",
        f"- output_param_total: {stats['output_param_total']}",
        f"- body_skipped_too_large_or_nondict: {stats['body_skipped_too_large_or_nondict']}",
        "",
        "## Missing field counters",
    ]
    for k, v in sorted(missing.items()):
        rep_lines.append(f"- {k}: {v}")
    rep_lines.append("")
    rep_lines.append("## Sample issues")
    for s in sample_issues[:20]:
        rep_lines.append(f"- {s}")
    (out_dir / "cleaning_report.md").write_text("\n".join(rep_lines) + "\n", encoding="utf-8")
    return {"stats": dict(stats), "missing": dict(missing), "tools": cleaned_rows}


def _fine_role_rule(name: str, desc: str, api_name: str, path_key: str) -> str:
    """阶段 03兜底规则：当 LLM 不可用或返回异常时，使用关键词规则提取 fine_role。"""
    n = norm_name(name)
    text = f"{name} {desc} {api_name} {path_key}".lower()
    if "asset_id" in n or "asset id" in text:
        return "asset_id"
    if "order_id" in n or "order id" in text:
        return "order_id"
    if "project_uuid" in n or "project uuid" in text:
        return "project_uuid"
    if "vault_id" in n:
        return "vault_id"
    if "marketplace_uuid" in n:
        return "marketplace_uuid"
    if "token_id" in n:
        return "token_id"
    if "sequence_id" in n:
        return "sequence_id"
    if "contract_address" in n:
        return "contract_address"
    if "wallet" in n:
        return "wallet_address"
    if "addr" in n or "address" in n:
        return "address"
    if n in {"r", "s"}:
        return "signature_rs"
    if "stark_key" in n:
        return "stark_key"
    if "key" in n:
        return "crypto_key"
    if "image" in n:
        return "image_blob"
    if "file" in n:
        return "file_blob"
    if "start" in n:
        return "start_marker"
    if "end" in n:
        return "end_marker"
    if "page" in n:
        return "page_cursor"
    if "json" in n:
        return "json_payload"
    if "data" in n:
        return "data_payload"
    if "message" in n:
        return "message_text"
    if "text" in n:
        return "text_payload"
    return n if n else "generic_slot"


def _fine_role(name: str, desc: str, api_name: str, path_key: str) -> str:
    """阶段 03主逻辑：优先调用千问生成细粒度 fine_role，规则函数仅作兜底。"""
    cache_key = json.dumps(
        {
            "name": name,
            "desc": desc,
            "api_name": api_name,
            "path_key": path_key,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    if cache_key in _FINE_ROLE_CACHE:
        return _FINE_ROLE_CACHE[cache_key]

    api_key = os.environ.get("QWEN_API_KEY") or os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        role = _fine_role_rule(name, desc, api_name, path_key)
        _FINE_ROLE_CACHE[cache_key] = role
        return role

    system_prompt = (
        "你是 API 参数语义归一化助手。"
        "请输出一个英文 fine_role，用于表示参数的细粒度语义对象。"
        "要求："
        "1) 只输出一个 token；"
        "2) 必须是小写英文+下划线（snake_case）；"
        "3) 语义尽量具体，避免 identifier/address 这类过粗标签；"
        "4) 不要输出解释、标点、JSON。"
    )
    user_prompt = (
        f"param_name={name}\n"
        f"param_desc={desc or '(none)'}\n"
        f"api_name={api_name}\n"
        f"path_key={path_key}\n"
        "请输出 fine_role。"
    )
    payload = {
        "model": QWEN_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
    }
    req = Request(
        QWEN_API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
        content = (
            body.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
            .lower()
        )
        role = norm_name(content)
        if role and role not in {"identifier", "address", "key", "data"}:
            _FINE_ROLE_CACHE[cache_key] = role
            return role
    except Exception:
        pass

    role = _fine_role_rule(name, desc, api_name, path_key)
    _FINE_ROLE_CACHE[cache_key] = role
    return role


def _build_semantic_description(
    name: str,
    desc: str,
    api_name: str,
    path_key: str,
    io_kind: str,
    value_type: str,
) -> str:
    """阶段 02：调用千问（含兜底）生成参数的一句话中文语义描述。"""
    cache_key = json.dumps(
        {
            "name": name,
            "desc": desc,
            "api_name": api_name,
            "path_key": path_key,
            "io_kind": io_kind,
            "value_type": norm_type(value_type),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    if cache_key in _SEMANTIC_DESC_CACHE:
        return _SEMANTIC_DESC_CACHE[cache_key]

    api_key = os.environ.get("QWEN_API_KEY") or os.environ.get("DASHSCOPE_API_KEY")
    fine = _fine_role(name, desc, api_name, path_key)
    io_text = "输入参数" if io_kind.startswith("input") else "输出参数"
    desc_part = f"；原始说明：{desc.strip()}" if desc else ""

    # 无 key 时兜底：保持流程可运行，但建议配置 QWEN_API_KEY / DASHSCOPE_API_KEY
    if not api_key:
        fallback = (
            f"{name} 是接口 {api_name}（{path_key}）的{io_text}，类型为 {norm_type(value_type)}，"
            f"用于表达 {fine}{desc_part}。"
        )
        _SEMANTIC_DESC_CACHE[cache_key] = fallback
        return fallback

    system_prompt = (
        "你是 API 参数语义标注助手。请根据给定上下文，输出一句中文语义描述。"
        "要求：只输出一句话；不输出 JSON；不输出字段名；不解释推理过程；"
        "尽量说明该参数在该接口中表示什么对象/含义及用途。"
    )
    user_prompt = (
        f"参数名: {name}\n"
        f"参数原始描述: {desc or '(无)'}\n"
        f"接口名: {api_name}\n"
        f"接口路径: {path_key}\n"
        f"输入输出类型: {io_kind}\n"
        f"值类型: {norm_type(value_type)}\n"
        "请给出一句中文语义描述。"
    )

    payload = {
        "model": QWEN_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
    }
    req = Request(
        QWEN_API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
        content = (
            body.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        if content:
            _SEMANTIC_DESC_CACHE[cache_key] = content
            return content
    except Exception:
        pass

    fallback = (
        f"{name} 是接口 {api_name}（{path_key}）的{io_text}，类型为 {norm_type(value_type)}，"
        f"用于表达 {fine}{desc_part}。"
    )
    _SEMANTIC_DESC_CACHE[cache_key] = fallback
    return fallback


def _extract_fine_role_from_description(
    semantic_description: str,
    fallback_name: str,
    api_name: str = "",
    path_key: str = "",
) -> str:
    """阶段 03：从语义描述与原字段中提取可归一化的 fine_role。"""
    role = _fine_role(fallback_name, semantic_description or "", api_name, path_key)
    return role or "generic_slot"


def _flatten_body_keys(d: dict[str, Any], prefix: str = "", depth: int = 0, max_depth: int = 2) -> list[tuple[str, Any]]:
    """阶段 01辅助：递归展开 body 键路径（当前主流程未强依赖）。"""
    out: list[tuple[str, Any]] = []
    if depth > max_depth:
        return out
    for k, v in d.items():
        if not isinstance(k, str):
            continue
        path = f"{prefix}.{k}" if prefix else k
        out.append((path, v))
        if isinstance(v, dict):
            out.extend(_flatten_body_keys(v, path, depth + 1, max_depth))
    return out


def stage_semantic_completion(cleaned_tools: list[dict[str, Any]], out_dir: Path) -> dict[str, Any]:
    """阶段 02：为输入/输出参数补充 semantic_description，并生成阶段报告。"""
    completed = json.loads(json.dumps(cleaned_tools, ensure_ascii=False))
    stats = Counter()
    filled_counter = Counter()

    total_params = _count_semantic_completion_params(completed)
    pbar = _progress_bar(total_params, "Stage 02 semantic_description")
    try:
        for t in completed:
            for api in t.get("apis", []):
                # 1) 输入参数语义补全：补的是“描述信息”，不做归一化
                for sec in ["required_parameters", "optional_parameters"]:
                    for prm in api.get(sec, []):
                        io_kind = "input_required" if sec == "required_parameters" else "input_optional"
                        sem_desc = _build_semantic_description(
                            prm.get("name", ""),
                            prm.get("description") or "",
                            api.get("name", ""),
                            api.get("path_key", ""),
                            io_kind,
                            prm.get("value_type", "STRING"),
                        )
                        prm["semantic_description"] = sem_desc
                        prm["semantic_source"] = "name_desc_context"
                        filled_counter["input_semantic_description"] += 1
                        stats["input_param_semantic_filled"] += 1
                        pbar.update(1)

                # 2) 输出参数语义补全（从 body 键路径 + API 上下文）
                new_outputs = []
                for ok in api.get("output_keys_sample", []):
                    key_name = ok.get("name", "")
                    row = dict(ok)
                    sem_desc = _build_semantic_description(
                        key_name,
                        "",
                        api.get("name", ""),
                        api.get("path_key", ""),
                        "output_sample",
                        row.get("value_type", "STRING"),
                    )
                    row["semantic_description"] = sem_desc
                    row["semantic_source"] = "output_key_context"
                    new_outputs.append(row)
                    filled_counter["output_semantic_description"] += 1
                    stats["output_param_semantic_filled"] += 1
                    pbar.update(1)
                api["output_keys_sample"] = new_outputs

                # 3) 额外记录：若输出描述里都没抽到 fine_role，则打标记
                if new_outputs and all(
                    _extract_fine_role_from_description(
                        o.get("semantic_description", ""),
                        o.get("name", ""),
                        api.get("name", ""),
                        api.get("path_key", ""),
                    )
                    == "generic_slot"
                    for o in new_outputs
                ):
                    api["output_semantic_needs_review"] = True
                    stats["api_output_all_generic_slot"] += 1
    finally:
        pbar.close()

    write_jsonl(out_dir / "semantic_completed_tools.jsonl", completed)
    rep = [
        "# SemanticCompletion Report",
        "",
        "- stage: SemanticCompletion",
        "- goal: 在归一化前补全参数语义提示（输入+输出）",
        f"- input_param_semantic_filled: {stats['input_param_semantic_filled']}",
        f"- output_param_semantic_filled: {stats['output_param_semantic_filled']}",
        f"- api_output_all_generic_slot: {stats['api_output_all_generic_slot']}",
        "",
        "## semantic enrichment counters",
    ]
    for k, v in filled_counter.most_common():
        rep.append(f"- {k}: {v}")
    (out_dir / "semantic_completion_report.md").write_text("\n".join(rep) + "\n", encoding="utf-8")
    return {"tools": completed, "stats": dict(stats), "role_counter": dict(filled_counter)}


def stage_preprocess(cleaned_tools: list[dict[str, Any]], out_dir: Path) -> dict[str, Any]:
    """阶段 03：从语义描述中抽取 fine_role，完成 canonical 归一化与映射输出。"""
    enriched: list[dict[str, Any]] = []
    norm_map: dict[str, dict[str, Any]] = {}
    role_counter = Counter()
    confidence_counter = Counter()
    canonical_counter = Counter()
    review_rows: list[dict[str, Any]] = []

    total_rows = _count_preprocess_param_rows(cleaned_tools)
    pbar = _progress_bar(total_rows, "Stage 03 fine_role + canonical")
    try:
        for t in cleaned_tools:
            domain = norm_name(t.get("tool_name", "tool"))
            for api in t.get("apis", []):
                api_name = api.get("name", "")
                path_key = api.get("path_key", "")
                for sec, io_kind in [
                    ("required_parameters", "input_required"),
                    ("optional_parameters", "input_optional"),
                    ("output_keys_sample", "output_sample"),
                ]:
                    for prm in api.get(sec, []):
                        raw_name = prm.get("name", "")
                        value_type = prm.get("value_type", "STRING")
                        desc = prm.get("description") or ""
                        sem_desc = prm.get("semantic_description") or ""
                        fine = _extract_fine_role_from_description(sem_desc, raw_name, api_name, path_key)
                        if fine and fine != "generic_slot":
                            conf = "high"
                        else:
                            fine = _fine_role(raw_name, desc, api_name, path_key)
                            conf = "low" if fine == "generic_slot" else "medium"
                        cid = canonical_id(value_type, fine or "generic_slot", domain)
                        rec = {
                            "tool_name": t.get("tool_name"),
                            "host": t.get("host"),
                            "api_name": api_name,
                            "api_path_key": path_key,
                            "io_kind": io_kind,
                            "raw_param_name": raw_name,
                            "raw_param_name_norm": prm.get("name_norm") or norm_name(raw_name),
                            "value_type": value_type,
                            "semantic_description": sem_desc,
                            "semantic_role_fine": fine,
                            "semantic_role": fine,
                            "canonical_param_id": cid,
                            "norm_confidence": conf,
                        }
                        enriched.append(rec)
                        role_counter[fine or "generic_slot"] += 1
                        confidence_counter[conf] += 1
                        canonical_counter[cid] += 1
                        norm_map[f"{api_name}|{io_kind}|{raw_name}|{value_type}"] = {
                            "semantic_description": sem_desc,
                            "semantic_role_fine": fine,
                            "semantic_role": fine,
                            "canonical_param_id": cid,
                            "norm_confidence": conf,
                        }
                        if conf == "low":
                            review_rows.append(rec)
                        pbar.update(1)
    finally:
        pbar.close()

    write_jsonl(out_dir / "parameters_enriched.jsonl", enriched)
    write_json(out_dir / "normalization_map.json", norm_map)
    write_jsonl(out_dir / "review_queue.jsonl", review_rows)

    rep = [
        "# Preprocess Report",
        "",
        f"- enriched_parameter_rows: {len(enriched)}",
        f"- unique_canonical_param_id: {len(canonical_counter)}",
        f"- review_queue_rows_low_confidence: {len(review_rows)}",
        "",
        "## Confidence distribution",
    ]
    for k, v in sorted(confidence_counter.items()):
        rep.append(f"- {k}: {v}")
    rep.append("")
    rep.append("## Top semantic roles")
    for role, cnt in role_counter.most_common(15):
        rep.append(f"- {role}: {cnt}")
    rep.append("")
    rep.append("## Top canonical params")
    for cid, cnt in canonical_counter.most_common(20):
        rep.append(f"- {cid}: {cnt}")
    (out_dir / "preprocess_report.md").write_text("\n".join(rep) + "\n", encoding="utf-8")

    return {
        "enriched_count": len(enriched),
        "canonical_count": len(canonical_counter),
        "review_count": len(review_rows),
        "confidence": dict(confidence_counter),
        "role_counter": dict(role_counter),
        "enriched_rows": enriched,
    }


def stage_rebuild_v2(
    cleaned_tools: list[dict[str, Any]],
    enriched_rows: list[dict[str, Any]],
    out_dir: Path,
    category: str,
) -> dict[str, Any]:
    """阶段 04：基于 canonical 参数重建 v4 KG；depends_on 采用跨工具 match_key 匹配。"""
    # index: (api_name, api_path_key, io_kind, raw_param_name_norm, value_type) -> canonical
    enrich_idx: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for r in enriched_rows:
        enrich_idx[
            (
                r["api_name"],
                r["api_path_key"],
                r["io_kind"],
                r["raw_param_name_norm"],
                r["value_type"],
            )
        ] = r

    nodes: list[dict[str, Any]] = [{"id": f"category:{category}", "node_type": "category", "label": category}]
    edges: list[dict[str, Any]] = []

    api_records: dict[str, dict[str, Any]] = {}
    output_match_keys_by_api: dict[str, list[str]] = defaultdict(list)
    input_match_keys_by_api: dict[str, list[str]] = defaultdict(list)
    canonical_aliases: dict[str, set[str]] = defaultdict(set)
    canonical_type_role: dict[str, tuple[str, str]] = {}
    tool_score: dict[str, dict[str, Any] | None] = {}

    def tool_id(stem: str) -> str:
        return f"tool:{category}:{stem}"

    for t in cleaned_tools:
        stem = Path(t["source_file"]).stem
        tid = tool_id(stem)
        nodes.append(
            {
                "id": tid,
                "node_type": "tool",
                "tool_name": t.get("tool_name"),
                "host": t.get("host"),
                "source_relpath": f"{category}/{t['source_file']}",
                "home_url": t.get("home_url"),
                "pricing": t.get("pricing"),
                "score": t.get("score"),
            }
        )
        tool_score[tid] = t.get("score")
        edges.append({"edge_type": "category_to_tool", "src": f"category:{category}", "dst": tid})

        for a in t.get("apis", []):
            aid = stable_api_id(t.get("host") or "", a.get("url") or "", a.get("method") or "GET", a["index_in_tool"])
            nodes.append(
                {
                    "id": aid,
                    "node_type": "api",
                    "name": a.get("name"),
                    "method": a.get("method"),
                    "url": a.get("url"),
                    "path_key": api_path_key(a.get("url") or "", a.get("method") or "GET"),
                    "tool_id": tid,
                    "index_in_tool": a["index_in_tool"],
                }
            )
            edges.append({"edge_type": "tool_to_api", "src": tid, "dst": aid})
            api_records[aid] = {"tool_id": tid, "name": a.get("name"), "path_key": a.get("path_key")}

            for sec, io_kind, role in [
                ("required_parameters", "input_required", "required"),
                ("optional_parameters", "input_optional", "optional"),
            ]:
                for prm in a.get(sec, []):
                    k = (
                        a.get("name"),
                        a.get("path_key"),
                        io_kind,
                        prm.get("name_norm") or norm_name(prm.get("name", "")),
                        prm.get("value_type", "STRING"),
                    )
                    er = enrich_idx.get(k)
                    if not er:
                        continue
                    match_key = f"{norm_type(er['value_type'])}:{er['semantic_role']}"
                    pid = global_parameter_node_id(er["value_type"], er["semantic_role"])
                    input_match_keys_by_api[aid].append(match_key)
                    canonical_aliases[pid].add(prm.get("name", ""))
                    canonical_type_role[pid] = (er["value_type"], er["semantic_role"])
                    edges.append(
                        {
                            "edge_type": "parameter_to_api",
                            "role": role,
                            "src": pid,
                            "dst": aid,
                        }
                    )

            for prm in a.get("output_keys_sample", []):
                k = (
                    a.get("name"),
                    a.get("path_key"),
                    "output_sample",
                    prm.get("name_norm") or norm_name(prm.get("name", "")),
                    prm.get("value_type", "STRING"),
                )
                er = enrich_idx.get(k)
                if not er:
                    continue
                match_key = f"{norm_type(er['value_type'])}:{er['semantic_role']}"
                pid = global_parameter_node_id(er["value_type"], er["semantic_role"])
                output_match_keys_by_api[aid].append(match_key)
                canonical_aliases[pid].add(prm.get("name", ""))
                canonical_type_role[pid] = (er["value_type"], er["semantic_role"])
                edges.append({"edge_type": "api_to_parameter", "src": aid, "dst": pid})

    # add normalized parameter nodes
    for pid in sorted(canonical_aliases.keys()):
        value_type, role = canonical_type_role.get(pid, ("STRING", "generic_slot"))
        mid = pid.removeprefix("parameter_norm:")
        nodes.append(
            {
                "id": pid,
                "node_type": "parameter",
                "param_name": role,
                "value_type": value_type,
                "match_key": mid,
                "slot_kind": "global_type_fine_role",
                "aliases": sorted(a for a in canonical_aliases[pid] if a),
            }
        )

    def edge_cost_prior(src_api: str, dst_api: str) -> float:
        t1 = api_records.get(src_api, {}).get("tool_id")
        t2 = api_records.get(dst_api, {}).get("tool_id")
        lat = []
        for t in (t1, t2):
            sc = tool_score.get(t) if t else None
            if isinstance(sc, dict) and sc.get("avgLatency") is not None:
                try:
                    lat.append(float(sc["avgLatency"]))
                except Exception:
                    pass
        base = max(lat) / 1000.0 if lat else 0.5
        return round(base + 0.15, 4)

    def success_prior(src_api: str, dst_api: str) -> float:
        t1 = api_records.get(src_api, {}).get("tool_id")
        t2 = api_records.get(dst_api, {}).get("tool_id")
        rates = []
        for t in (t1, t2):
            sc = tool_score.get(t) if t else None
            if isinstance(sc, dict) and sc.get("avgSuccessRate") is not None:
                try:
                    rates.append(float(sc["avgSuccessRate"]) / 100.0)
                except Exception:
                    pass
        if not rates:
            return 0.5
        return round(sum(rates) / len(rates), 4)

    # depends_on: output/input match_key 相交（跨工具/跨 category 可连接）
    api_ids = sorted(api_records.keys())
    for src in api_ids:
        out_set = set(output_match_keys_by_api.get(src, []))
        if not out_set:
            continue
        for dst in api_ids:
            if src == dst:
                continue
            in_set = set(input_match_keys_by_api.get(dst, []))
            inter = sorted(out_set & in_set)
            if not inter:
                continue
            match_key = inter[0]
            parts = match_key.split(":")
            if len(parts) >= 2:
                role = parts[1]
            else:
                role = match_key
            edges.append(
                {
                    "edge_type": "depends_on",
                    "src": src,
                    "dst": dst,
                    "mapping_signature": f"match_key:{match_key}",
                    "match_confidence": 1.0,
                    "semantic_role": role,
                    "est_cost": edge_cost_prior(src, dst),
                    "success_freq_prior": success_prior(src, dst),
                }
            )

    write_jsonl(out_dir / "nodes.jsonl", nodes)
    write_jsonl(out_dir / "edges.jsonl", edges)

    ec = Counter(e["edge_type"] for e in edges)
    rep = [
        f"# Build report ({category}_v4_cross_tool_depends)",
        "",
        "- **method**: global parameter nodes by TYPE:fine_role + depends_on by same match_key",
        f"- **nodes_total**: {len(nodes)}",
        f"- **edges_total**: {len(edges)}",
        f"- **parameter_nodes_canonical**: {sum(1 for n in nodes if n.get('node_type') == 'parameter')}",
        "",
        "## edges_by_type",
    ]
    for k in sorted(ec):
        rep.append(f"- {k}: {ec[k]}")
    (out_dir / "build_report.md").write_text("\n".join(rep) + "\n", encoding="utf-8")

    schema = {
        "version": "v4_cross_tool_depends",
        "parameter_node_mode": "global_by_type_fine_role",
        "parameter_node_id": "parameter_norm:<TYPE>:<fine_role>",
        "canonical_param_id_stage03": "<TYPE>:<fine_role>:<tool_domain>",
        "depends_on_match_key": "<TYPE>:<fine_role>",
        "depends_on_rule": "API output match_key intersects API input match_key (cross-tool/category allowed)",
    }
    write_json(out_dir / "schema_notes_v4.json", schema)
    return {
        "nodes_total": len(nodes),
        "edges_total": len(edges),
        "parameter_nodes": sum(1 for n in nodes if n.get("node_type") == "parameter"),
        "edge_counts": dict(ec),
    }


def build_compare_md(
    target_root: Path,
    clean_info: dict[str, Any],
    semantic_info: dict[str, Any],
    pre_info: dict[str, Any],
    v2_info: dict[str, Any],
    category: str,
    out_tag: str,
) -> None:
    """汇总报告：生成 PROCESS_COMPARE.md，展示各阶段统计对比。"""
    stats = clean_info["stats"]
    md = [
        f"# {category}_sample 数据处理分步对比",
        "",
        "## 0. 本次流程",
        f"- 数据源复制：`00_source_copy/tools_{category}`（来自 `tools/{category}`）",
        f"- 基线复制：`00_source_copy/kg_baseline`（来自 `out/{category}_sample`，若存在）",
        "- 清洗结果：`01_cleaned/cleaned_tools.jsonl` + `cleaning_report.md`",
        "- 语义补全结果：`02_semantic_completion/semantic_completed_tools.jsonl` + `semantic_completion_report.md`",
        "- 预处理结果：`03_preprocessed/parameters_enriched.jsonl` + `normalization_map.json` + `preprocess_report.md`",
        "",
        "## 1. 阶段 A（原 API 数据清洗）",
        f"- JSON 文件数：`{stats.get('json_seen', 0)}`",
        f"- 可用 Tool 数：`{stats.get('tool_total', 0)}`",
        f"- API 数：`{stats.get('api_total', 0)}`",
        f"- 输入参数数：required `{stats.get('required_param_total', 0)}` + optional `{stats.get('optional_param_total', 0)}`",
        f"- 输出样本参数数：`{stats.get('output_param_total', 0)}`（受 body 覆盖率影响）",
        "",
        "## 2. 阶段 B（SemanticCompletion 语义补全）",
        f"- 输入参数语义补全数：`{semantic_info['stats'].get('input_param_semantic_filled', 0)}`",
        f"- 输出参数语义补全数：`{semantic_info['stats'].get('output_param_semantic_filled', 0)}`",
        f"- 输出全 generic_slot 的 API 数：`{semantic_info['stats'].get('api_output_all_generic_slot', 0)}`",
        "",
        "### semantic enrichment 计数（前 12）",
    ]
    sem_sorted = sorted(semantic_info["role_counter"].items(), key=lambda x: x[1], reverse=True)[:12]
    for k, v in sem_sorted:
        md.append(f"- {k}: {v}")
    md += [
        "",
        "## 3. 阶段 C（语义解释 + 归一化）",
        f"- 参数行（输入+输出）：`{pre_info['enriched_count']}`",
        f"- 规范参数 ID 去重后：`{pre_info['canonical_count']}`",
        f"- 低置信度待复核：`{pre_info['review_count']}`",
        "",
        "### 置信度分布",
    ]
    for k, v in sorted(pre_info["confidence"].items()):
        md.append(f"- {k}: {v}")
    md += ["", "### Top 语义角色（前 12）"]
    role_sorted = sorted(pre_info["role_counter"].items(), key=lambda x: x[1], reverse=True)[:12]
    for k, v in role_sorted:
        md.append(f"- {k}: {v}")
    md += [
        "",
        "## 4. 阶段 D（v4 跨工具依赖 KG 重建）",
        f"- v4 节点总数：`{v2_info['nodes_total']}`",
        f"- v4 边总数：`{v2_info['edges_total']}`",
        f"- v4 归一化 Parameter 节点数：`{v2_info['parameter_nodes']}`",
        f"- v4 depends_on：`{v2_info['edge_counts'].get('depends_on', 0)}`",
        f"- v4 输出目录：`DataProcess/out/{out_tag}/`（保留历史版本供对比）",
        "",
        "## 5. 你关心的“参数传递与一致性”目前落地情况",
        "- 已把参数从“仅名字+类型”提升为“语义角色 + 规范参数ID + 置信度”。",
        "- `review_queue.jsonl` 已单列低置信度项，可人工修订后再回写规则。",
        "- 已基于 `canonical_param_id` 重建 Parameter 节点与 depends_on（阶段 C 已落地）。",
        "- 下一步建议：人工抽查低置信度与 depends_on 误连，再微调角色规则。",
        "",
    ]
    (target_root / "PROCESS_COMPARE.md").write_text("\n".join(md), encoding="utf-8")


def main() -> None:
    """主流程入口：顺序执行 00->01->02->03->04 并产出总对比报告。"""
    ap = argparse.ArgumentParser(description="Run DataProcess pipeline for one category")
    ap.add_argument("--category", default="Cryptography", help="Category name under tools/")
    ap.add_argument("--version-tag", default="v4", help="Output version tag")
    ap.add_argument(
        "--progress-file",
        type=Path,
        default=None,
        help="进度快照文件（非 TTY/Agent 运行时可在编辑器中打开查看）；不设则用默认路径",
    )
    ap.add_argument("--no-progress-file", action="store_true", help="不写入进度快照文件")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    category = args.category
    out_tag = f"{category}_sample_{args.version_tag}"
    source_tools = repo_root / "tools" / category
    baseline = repo_root / "static_kg" / "out" / f"{category}_sample"
    target_root = repo_root / "static_kg" / "DataProcess" / f"{category}_sample"
    out_v2 = repo_root / "static_kg" / "DataProcess" / "out" / out_tag

    if args.no_progress_file:
        set_pipeline_progress_log(None)
    elif args.progress_file is not None:
        set_pipeline_progress_log(args.progress_file)
    else:
        set_pipeline_progress_log(target_root / "pipeline_progress.txt")

    copy_source(source_tools, baseline, target_root, category)

    clean_out = target_root / "01_cleaned"
    clean_info = stage_clean(target_root / "00_source_copy" / f"tools_{category}", clean_out)

    sem_out = target_root / "02_semantic_completion"
    semantic_info = stage_semantic_completion(clean_info["tools"], sem_out)

    pre_out = target_root / "03_preprocessed"
    pre_info = stage_preprocess(semantic_info["tools"], pre_out)

    v2_info = stage_rebuild_v2(clean_info["tools"], pre_info["enriched_rows"], out_v2, category)
    build_compare_md(target_root, clean_info, semantic_info, pre_info, v2_info, category, out_tag)
    print(target_root)


if __name__ == "__main__":
    main()
