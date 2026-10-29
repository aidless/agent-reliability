#!/usr/bin/env python3
"""用 mcp-guard 的规则包扫真实 MCP 工具定义语料（corpus/）。

语料由 `scripts/collect_mcp_tools.py` 采集：真实 server 的 `tools/list` 输出，
版本钉死，采集过程记录在语料的 `isolation` 字段里。

这个脚本只回答一个问题：**规则包在真实良性工具上误报多少。**
它不能回答召回率——语料里没有一条毒工具。

用法：
    python3 scripts/scan_real_corpus.py                       # 默认读最新 corpus/
    python3 scripts/scan_real_corpus.py --corpus corpus/x.json --mcp-guard-repo ~/mcp-guard
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# "看着敏感但没命中"的线索词：用来展示规则是有意收窄的，不是漏看
NEAR_MISS_WORDS = ("key", "token", "secret", "credential", "password",
                   "env", "ssh", "file", "path", "url", "http", "shell", "exec")


def latest_corpus() -> pathlib.Path:
    files = sorted(glob.glob(str(ROOT / "corpus" / "mcp-tools-*.json")))
    if not files:
        raise SystemExit("corpus/ 下没有语料，先跑 scripts/collect_mcp_tools.py")
    return pathlib.Path(files[-1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=None)
    ap.add_argument("--mcp-guard-repo", default=str(pathlib.Path.home() / "mcp-guard"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--fail-if-flagged", action="store_true",
                    help="有任何工具被 flag 就以退出码 1 结束（CI 用来锁住\"真实良性工具零误报\"）")
    args = ap.parse_args()

    sys.path.insert(0, args.mcp_guard_repo)
    from guard.scan import digest_tool, scan_tool  # noqa: E402

    corpus_path = pathlib.Path(args.corpus) if args.corpus else latest_corpus()
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))

    rows, near_misses = [], []
    for server in corpus["servers"]:
        for tool in server["tools"]:
            result = scan_tool(tool)
            text = " ".join([tool.get("name") or "", tool.get("description") or ""]).lower()
            row = {
                "server_id": server["server_id"],
                "package": server["package"],
                "version": server["version"],
                "tool": tool["name"],
                "digest": digest_tool(tool),
                "flagged": result["flagged"],
                "rules": [h["rule"] for h in result["hits"]],
                "anchors": [h["anchor"] for h in result["hits"]],
                "desc_len": len(tool.get("description") or ""),
            }
            rows.append(row)
            if not result["flagged"]:
                words = [w for w in NEAR_MISS_WORDS if w in text]
                if words:
                    near_misses.append({"server_id": server["server_id"],
                                        "tool": tool["name"], "words": words,
                                        "desc_len": row["desc_len"]})

    total = len(rows)
    flagged = [r for r in rows if r["flagged"]]
    per_server = [
        {"server_id": s["server_id"], "package": s["package"], "version": s["version"],
         "tools": s["tool_count"],
         "flagged": sum(1 for r in rows if r["server_id"] == s["server_id"] and r["flagged"])}
        for s in corpus["servers"]
    ]
    rule_counts = {}
    for r in flagged:
        for rule in r["rules"]:
            rule_counts[rule] = rule_counts.get(rule, 0) + 1

    report = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "corpus_file": corpus_path.name,
        "corpus_generated_utc": corpus.get("generated_utc"),
        "servers": len(corpus["servers"]),
        "total_tools": total,
        "flagged_tools": len(flagged),
        "flag_rate": round(len(flagged) / total, 4) if total else 0.0,
        "rule_counts": rule_counts,
        "per_server": per_server,
        "near_misses": near_misses,
        "tools": rows,
        "interpretation": (
            "这 53 个工具都来自官方参考 server，都是良性工具。"
            "所以本表只能读成误报率，不能读成召回率——语料里没有毒工具。"
        ),
    }
    out = pathlib.Path(args.out) if args.out else (
        ROOT / "reports" /
        f"real-mcp-scan-{dt.date.today().strftime('%Y%m%d')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"语料 {corpus_path.name}：{report['servers']} 个 server / {total} 个工具")
    print(f"被 flag：{len(flagged)} / {total} = {report['flag_rate']}")
    for s in per_server:
        print(f"  {s['server_id']:<22} {s['flagged']}/{s['tools']}")
    print(f"\n写入 {out}")
    if args.fail_if_flagged and flagged:
        print(f"::error::真实语料上出现 {len(flagged)} 个误报", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
