#!/usr/bin/env python3
"""联合裁决的完整组合表：把决策函数的**结构**完整刻画出来。

现在 `TestDecisionCombos` 只手写了 9 个有代表性的组合。这个脚本把证据字段的
笛卡尔积全枚举一遍，对每个**可行**组合跑 `engine.evaluate`，输出：

  - 裁决分布（PASS / REVIEW / FAIL / BLOCK / INCOMPLETE 各多少）
  - 与两个基线的差异：
        基线 A「只看 naive 检查器」  naive 全绿就算通过
        基线 B「只看权威分」         reference_check 满分就算通过
    关键数字：**基线 A 判 PASS 的组合里，联合层把多少降级了**
  - 每条规则触发多少次

读法（很重要）：
本表刻画的是**决策函数**，不是"这套规则在世界上的效力"。
它回答"同样的证据喂进去，加不加工具面，结论会不会不同"，
不回答"真实世界里有多少这种证据"——后者要靠真实的 run 语料。
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import itertools
import json
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "rules"))

import engine  # noqa: E402

# 维度与取值。刻意只用二元/三元：要的是"每种证据状态被分到哪一类"，
# 不是把连续量也扫一遍。
DIMS = {
    "tool_flagged": [0, 2],
    "tool_drift_alerts": [0, 1],
    "drift_new": [0, 1],
    "drift_changed": [0, 1],
    "audit_present": [True, False],
    "audit_rate_is_1": [True, False],
    "audit_naive_all_green": [True, False, None],
    "audit_excluded": [0, 1],
    "baseline_had_audit": [False, True],
    "attack": ["none", "some", "zero"],
}


def feasible(combo: dict) -> bool:
    """排除内部矛盾的证据状态；被排除不等于被判通过。"""
    if combo["drift_new"] and not combo["tool_drift_alerts"]:
        return False
    if combo["drift_changed"] and not combo["tool_drift_alerts"]:
        return False
    if not combo["audit_present"]:
        if combo["audit_rate_is_1"]:
            return False
        if combo["audit_naive_all_green"] is not None:
            return False
        if combo["audit_excluded"]:
            return False
    elif combo["audit_naive_all_green"] is None:
        return False          # 有输出面就一定有 naive 对照
    return True


def to_evidence(combo: dict) -> dict:
    present = combo["audit_present"]
    rate_is_1 = combo["audit_rate_is_1"] and present
    attack = combo["attack"]
    ev = {
        "tool_scanned": 4,
        "tool_flagged": combo["tool_flagged"],
        "tool_flagged_names": ["x"] * combo["tool_flagged"],
        "tool_drift_alerts": combo["tool_drift_alerts"],
        "tool_drift_new_hits": combo["drift_new"],
        "tool_drift_changed_hits": combo["drift_changed"],
        "tool_drift_alarm": 1 if (combo["drift_new"] or combo["drift_changed"]) else 0,
        "tool_drift_unknown": 0,
        "tool_clean": combo["tool_flagged"] == 0 and combo["tool_drift_alerts"] == 0,
        "audit_present": present,
        "audit_total": 3,
        "audit_semantic_scored": 3 - combo["audit_excluded"] if present else 0,
        "audit_excluded": combo["audit_excluded"] if present else 0,
        "audit_runtime_errors": combo["audit_excluded"] if present else 0,
        "audit_rate": (1.0 if rate_is_1 else 0.6667) if present else None,
        "audit_rate_is_1": bool(rate_is_1),
        "audit_naive_all_green": combo["audit_naive_all_green"] if present else None,
        "audit_naive_green": ("3/3" if combo["audit_naive_all_green"] else "2/3")
                             if present else "",
        "audit_unsupported_claims": 0,
        "missing_evidence_count": 0 if present else 1,
        "output_evidence_regressed": bool(combo["baseline_had_audit"] and not present),
        "attack_sim_present": attack != "none",
        "attack_samples": 50 if attack != "none" else 0,
        "attack_covered": {"none": 0, "some": 1, "zero": 0}[attack],
        "attack_uncovered": {"none": 0, "some": 49, "zero": 50}[attack],
    }
    ev["_missing_evidence"] = [] if present else ["output_audit"]
    return ev


def naive_baseline(ev: dict) -> str:
    """基线 A：只看 naive 检查器（非空 + 长度）。"""
    if ev["audit_naive_all_green"] is None:
        return "NO_EVIDENCE"
    return "PASS" if ev["audit_naive_all_green"] else "FAIL"


def authoritative_baseline(ev: dict) -> str:
    """基线 B：只看权威 reference_check 通过率。"""
    if not ev["audit_present"]:
        return "NO_EVIDENCE"
    return "PASS" if ev["audit_rate_is_1"] else "FAIL"


def build_matrix(rules: dict) -> dict:
    keys = list(DIMS)
    rows, excluded = [], 0
    for values in itertools.product(*(DIMS[k] for k in keys)):
        combo = dict(zip(keys, values))
        if not feasible(combo):
            excluded += 1
            continue
        ev = to_evidence(combo)
        d = engine.evaluate(rules, ev)
        rows.append({
            "combo": combo,
            "tool_clean": ev["tool_clean"],
            "verdict": d["verdict"],
            "rule_id": d["rule_id"],
            "matched": [m["id"] for m in d["matched_rules"]],
            "naive_baseline": naive_baseline(ev),
            "authoritative_baseline": authoritative_baseline(ev),
        })

    verdict_counts = Counter(r["verdict"] for r in rows)
    rule_counts = Counter(m for r in rows for m in r["matched"])

    def demotion(baseline_key: str) -> dict:
        base_pass = [r for r in rows if r[baseline_key] == "PASS"]
        demoted = [r for r in base_pass if r["verdict"] != "PASS"]
        by_verdict = Counter(r["verdict"] for r in demoted)
        return {
            "baseline_pass": len(base_pass),
            "demoted": len(demoted),
            "still_pass": len(base_pass) - len(demoted),
            "demote_rate": round(len(demoted) / len(base_pass), 4) if base_pass else 0.0,
            "demoted_into": dict(by_verdict),
        }

    # 反向：联合判 PASS，但某个基线判 FAIL（基线的过度告警）
    joint_pass = [r for r in rows if r["verdict"] == "PASS"]
    return {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "rules_version": rules.get("version"),
        # 规则文件的内容哈希：version 字段是手写的，不足以溯源。
        "rules_file_sha256_16": hashlib.sha256(
            (ROOT / "rules" / "joint_verdict.json").read_bytes()).hexdigest()[:16],
        "verdict_precedence": rules.get("verdict_precedence"),
        "dimensions": DIMS,
        "combos_total_raw": len(rows) + excluded,
        "combos_feasible": len(rows),
        "combos_excluded_infeasible": excluded,
        "verdict_counts": dict(verdict_counts),
        "rule_trigger_counts": dict(rule_counts),
        "naive_baseline": demotion("naive_baseline"),
        "authoritative_baseline": demotion("authoritative_baseline"),
        "joint_pass_vs_naive_fail": sum(
            1 for r in joint_pass if r["naive_baseline"] == "FAIL"),
        "joint_pass_vs_authoritative_fail": sum(
            1 for r in joint_pass if r["authoritative_baseline"] == "FAIL"),
        "evidence_deletion": evidence_deletion_check(rules, rows),
        "combos": rows,
    }


SEVERITY = {"PASS": 0, "REVIEW": 1, "FAIL": 2, "INCOMPLETE": 3, "BLOCK": 4}


def evidence_deletion_check(rules: dict, rows: list[dict]) -> dict:
    """系统性检查：把输出面证据删掉，裁决不能变轻。

    能变轻就意味着门禁可以被"删掉 audit/ 目录"绕过。分两类记：
      violations  —— 上一轮有输出面（有基线可比）却仍然变轻 = 不该发生
      unavoidable —— 上一轮也没有输出面，当前 run 自己无法知道删掉了什么
    2026-10-28 靠这条查出两件事：verdict_precedence 里 INCOMPLETE 排在 FAIL
    之下；以及 R2（假绿 BLOCK）完全依赖被删掉的证据 → 补了 R10 基线感知。
    """
    violations, examples, unavoidable = 0, [], 0
    for r in rows:
        c = r["combo"]
        if not c["audit_present"]:
            continue
        gone = dict(c, audit_present=False, audit_rate_is_1=False,
                    audit_naive_all_green=None, audit_excluded=0)
        if not feasible(gone):
            continue
        after = engine.evaluate(rules, to_evidence(gone))["verdict"]
        if SEVERITY[after] < SEVERITY[r["verdict"]]:
            if c["baseline_had_audit"]:
                violations += 1
                if len(examples) < 3:
                    examples.append({"before": r["verdict"], "after": after,
                                     "combo": c})
            else:
                unavoidable += 1
    return {"violations": violations, "examples": examples,
            "unavoidable_without_baseline": unavoidable}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    rules = engine.load_rules()
    matrix = build_matrix(rules)
    out = pathlib.Path(args.out) if args.out else (
        ROOT / "reports" /
        f"joint-decision-matrix-{dt.date.today().strftime('%Y%m%d')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)

    # 逐组合明细单独写成 TSV：比塞进 JSON 小一个数量级，也能直接 grep。
    combos = matrix.pop("combos")
    tsv = out.with_suffix(".tsv")
    keys = list(DIMS)
    header = keys + ["verdict", "rule_id", "matched", "naive_baseline",
                     "authoritative_baseline"]
    lines = ["\t".join(header)]
    for r in combos:
        row = [str(r["combo"][k]) for k in keys]
        row += [r["verdict"], r["rule_id"] or "", ",".join(r["matched"]),
                r["naive_baseline"], r["authoritative_baseline"]]
        lines.append("\t".join(row))
    tsv.write_text("\n".join(lines) + "\n", encoding="utf-8")

    matrix["combos_tsv"] = tsv.name
    out.write_text(json.dumps(matrix, ensure_ascii=False, indent=1), encoding="utf-8")

    n = matrix["naive_baseline"]
    a = matrix["authoritative_baseline"]
    print(f"可行组合 {matrix['combos_feasible']} / "
          f"原始 {matrix['combos_total_raw']}（排除内部矛盾 {matrix['combos_excluded_infeasible']}）")
    print("裁决分布:", matrix["verdict_counts"])
    print(f"基线 A（只看 naive 全绿）：{n['baseline_pass']} 个 PASS，"
          f"联合层降级 {n['demoted']} 个 = {n['demote_rate']}")
    print(f"基线 B（只看权威分）  ：{a['baseline_pass']} 个 PASS，"
          f"联合层降级 {a['demoted']} 个 = {a['demote_rate']}")
    print("规则触发次数:", dict(sorted(matrix["rule_trigger_counts"].items())))
    dl = matrix["evidence_deletion"]
    print(f"删证据不变量：有基线可比时违反 {dl['violations']} 对；"
          f"无基线不可知 {dl['unavoidable_without_baseline']} 对",
          "" if not dl["violations"] else f"  ← {dl['examples']}")
    print(f"\n写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
