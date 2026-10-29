#!/usr/bin/env python3
"""规则消融测量：把某条规则从规则包里摘掉，看指标怎么变。

用途：为 mcp-guard 的每一次规则改动留下一条"可复算的因果链"——
加规则之前的数字、之后的数字、以及"如果没有这条规则会漏掉哪个用例"。

用法：
    python3 scripts/measure_rule_ablation.py --repo /home/liuzewen/mcp-guard \
        --rule encoded-exfil

输出：JSON（stdout），含 with_rule / without_rule 两组指标与被漏掉的用例名。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys


def metrics(scan_tool, rows) -> dict:
    poison = [r for r in rows if r["label"] == "poison"]
    benign = [r for r in rows if r["label"] == "benign"]
    tp = sum(1 for c in poison if scan_tool(c)["flagged"])
    fp = sum(1 for c in benign if scan_tool(c)["flagged"])
    gold = sum(len(c.get("gold_rules", [])) for c in poison)
    hits = sum(
        len(set(c.get("gold_rules", [])) & {h["rule"] for h in scan_tool(c)["hits"]})
        for c in poison
    )
    missed = [c["name"] for c in poison if not scan_tool(c)["flagged"]]
    false_pos = [c["name"] for c in benign if scan_tool(c)["flagged"]]
    return {
        "n_poison": len(poison),
        "n_benign": len(benign),
        "recall_case": round(tp / max(1, len(poison)), 4),
        "fpr_benign": round(fp / max(1, len(benign)), 4),
        "recall_rule": round(hits / max(1, gold), 4),
        "missed_poison_cases": missed,
        "false_positive_cases": false_pos,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="/home/liuzewen/mcp-guard")
    ap.add_argument("--cases", default=None)
    ap.add_argument("--rule", required=True, help="要消融的规则 id")
    args = ap.parse_args()

    repo = pathlib.Path(args.repo).resolve()
    sys.path.insert(0, str(repo))
    from guard import rules as R
    from guard.scan import scan_tool

    cases_path = pathlib.Path(args.cases) if args.cases else repo / "tasks" / "cases.jsonl"
    rows = [
        json.loads(line)
        for line in cases_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    with_rule = metrics(scan_tool, rows)

    # 负对照：把该规则从规则包摘掉（在内存里改，不写文件）。
    saved_rules, saved_compiled = list(R.RULES), list(R._COMPILED)
    try:
        R.RULES = [r for r in R.RULES if r["id"] != args.rule]
        R._COMPILED = [
            (r["id"], r["severity"], [re.compile(p, re.I) for p in r["patterns"]], r["why"])
            for r in R.RULES
        ]
        without_rule = metrics(scan_tool, rows)
    finally:
        R.RULES, R._COMPILED = saved_rules, saved_compiled

    print(json.dumps({
        "repo": str(repo),
        "cases": str(cases_path),
        "ablated_rule": args.rule,
        "with_rule": with_rule,
        "without_rule": without_rule,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
