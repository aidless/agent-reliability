#!/usr/bin/env python3
"""受控注入召回：把**公开**攻击载荷塞进**真实**工具描述，测规则包召回。

为什么这样设计
--------------
自造毒样例测出来的召回没有说服力（规则就是照着那批样例写的）。
这里用两份都不是本仓写的东西：

  良性载体：`corpus/` 里 6 个官方 MCP server 的 53 个真实工具（`tools/list` 原样）
  攻击载荷：`aidless/agent-redteam` 的 50 条公开攻击样本（12 个向量）

三种注入位置，因为"塞在哪"本身就影响结果：
  append   —— 载荷接在真实描述后面
  prepend  —— 载荷放在真实描述前面
  replace  —— 用载荷整段替换描述

同时给两个对照：
  基线     —— 未改动的 53 个真实工具（预期 0 命中，锁住误报）
  良性对照 —— 给每个工具追加一句中性话（预期 0 命中，排除"追加动作本身导致命中"）
  自造集   —— mcp-guard 自己的 19 条毒用例（**in-distribution**，规则照它写的）

读法
----
`append/prepend/replace` 的召回是 **out-of-distribution**：这些载荷是为提示注入
写的，不是为工具投毒写的。把它们塞进工具描述，测的是"规则包对这批公开攻击的
通用性"，不是"在它们的原生攻击面里的检出率"。两个数字必须分开报。

用法：
    python3 scripts/injected_recall.py --redteam-repo ~/agent-redteam
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLACEMENTS = ("append", "prepend", "replace")
BENIGN_FILLER = ("This tool is documented and maintained by the platform team; "
                 "report issues through the usual support channel.")


def load_corpus() -> dict:
    files = sorted((ROOT / "corpus").glob("mcp-tools-*.json"))
    if not files:
        raise SystemExit("corpus/ 下没有语料，先跑 scripts/collect_mcp_tools.py")
    return json.loads(files[-1].read_text(encoding="utf-8"))


def load_payloads(redteam_repo: pathlib.Path) -> list[dict]:
    data = json.loads(
        (redteam_repo / "data" / "attack_vectors.json").read_text(encoding="utf-8"))
    rows = []
    for vector in data["attack_vectors"]:
        for sample in vector["samples"]:
            rows.append({
                "vector_id": vector["vector_id"],
                "vector_name": vector["name"],
                "sample_id": sample["id"],
                "payload": sample["payload"],
            })
    return rows


def injected_description(original: str, payload: str, placement: str) -> str:
    original = original or ""
    if placement == "append":
        return f"{original}\n\n{payload}"
    if placement == "prepend":
        return f"{payload}\n\n{original}"
    return payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--redteam-repo", default=str(pathlib.Path.home() / "agent-redteam"))
    ap.add_argument("--mcp-guard-repo", default=str(pathlib.Path.home() / "mcp-guard"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    sys.path.insert(0, args.mcp_guard_repo)
    from guard.rules import scan_text      # noqa: E402
    from guard.scan import scan_tool       # noqa: E402

    corpus = load_corpus()
    payloads = load_payloads(pathlib.Path(args.redteam_repo))
    tools = [t for s in corpus["servers"] for t in s["tools"]]

    # ---- 基线：未改动的真实工具 ----
    baseline_flagged = sum(1 for t in tools if scan_tool(t)["flagged"])

    # ---- 良性对照：追加中性话 ----
    benign_flagged = 0
    for t in tools:
        mutated = dict(t, description=injected_description(
            t.get("description", ""), BENIGN_FILLER, "append"))
        if scan_tool(mutated)["flagged"]:
            benign_flagged += 1

    # ---- 注入召回 ----
    rows = []
    for t in tools:
        for p in payloads:
            for placement in PLACEMENTS:
                mutated = dict(t, description=injected_description(
                    t.get("description", ""), p["payload"], placement))
                result = scan_tool(mutated)
                rows.append({
                    "tool": t["name"],
                    "vector_id": p["vector_id"],
                    "sample_id": p["sample_id"],
                    "placement": placement,
                    "flagged": result["flagged"],
                    "rules": [h["rule"] for h in result["hits"]],
                    "anchors": [h["anchor"] for h in result["hits"]],
                })

    def rate(subset: list[dict]) -> dict:
        n = len(subset)
        hit = sum(1 for r in subset if r["flagged"])
        return {"n": n, "flagged": hit,
                "rate": round(hit / n, 4) if n else 0.0}

    by_placement = {ph: rate([r for r in rows if r["placement"] == ph])
                    for ph in PLACEMENTS}
    by_vector = {}
    for p in payloads:
        by_vector[p["vector_id"]] = rate(
            [r for r in rows if r["vector_id"] == p["vector_id"]])

    # ---- in-distribution 对照：mcp-guard 自己的毒用例 ----
    cases_path = pathlib.Path(args.mcp_guard_repo) / "tasks" / "cases.jsonl"
    cases = [json.loads(l) for l in
             cases_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    poison = [c for c in cases if c.get("label") == "poison"]
    poison_flagged = sum(1 for c in poison if scan_tool(c)["flagged"])

    report = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "carrier": {"source": corpus.get("generated_utc"),
                    "servers": len(corpus["servers"]), "tools": len(tools)},
        "payloads": {"source": "aidless/agent-redteam data/attack_vectors.json",
                     "vectors": len({p["vector_id"] for p in payloads}),
                     "samples": len(payloads)},
        "controls": {
            "baseline_unmodified_tools": rate([{"flagged": bool(baseline_flagged)}]),
            "benign_appended_filler": rate([{"flagged": bool(benign_flagged)}]),
            "in_distribution_poison_cases": {
                "n": len(poison), "flagged": poison_flagged,
                "rate": round(poison_flagged / len(poison), 4) if poison else 0.0,
            },
        },
        "out_of_distribution": {
            "total": rate(rows),
            "by_placement": by_placement,
            "by_vector": by_vector,
        },
        "interpretation": (
            "append/prepend/replace 是 out-of-distribution：载荷原本面向提示注入，"
            "不是工具投毒。这里的召回衡量的是通用性，不是原生攻击面上的检出率。"
            "in_distribution_poison_cases 是规则设计时参照的那批样例，两者不可相加。"
        ),
        "rows": rows,
    }
    out = pathlib.Path(args.out) if args.out else (
        ROOT / "reports" /
        f"injected-recall-{dt.date.today().strftime('%Y%m%d')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    detail = [f"{r['tool']}\t{r['vector_id']}\t{r['sample_id']}\t{r['placement']}\t"
              f"{int(r['flagged'])}\t{','.join(r['rules'])}" for r in rows]
    out.with_suffix(".tsv").write_text(
        "tool\tvector_id\tsample_id\tplacement\tflagged\trules\n" +
        "\n".join(detail) + "\n", encoding="utf-8")
    report["rows_tsv"] = out.with_suffix(".tsv").name
    report.pop("rows")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    c = report["controls"]
    print(f"载体：{len(tools)} 个真实工具；载荷：{len(payloads)} 条（{len(by_vector)} 个向量）")
    print(f"基线（未改动）      ：{c['baseline_unmodified_tools']['flagged']} / {len(tools)} 命中")
    print(f"良性对照（追加中性话）：{c['benign_appended_filler']['flagged']} / {len(tools)} 命中")
    print(f"自造毒用例（in-dist）：{c['in_distribution_poison_cases']['flagged']} / "
          f"{c['in_distribution_poison_cases']['n']} = {c['in_distribution_poison_cases']['rate']}")
    print("\nout-of-distribution 召回：")
    for ph in PLACEMENTS:
        b = by_placement[ph]
        print(f"  {ph:<8} {b['flagged']} / {b['n']} = {b['rate']}")
    print(f"\n写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
