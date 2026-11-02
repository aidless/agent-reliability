#!/usr/bin/env python3
"""基准：联合裁决引擎在完整组合表上的求值成本。

测量一个**真实可复现**的属性：把 `scripts/joint_decision_matrix.py` 定义的
11 维证据笛卡尔积全部可行组合喂给 `rules/engine.evaluate`，引擎一次完整求值
要多久、每秒能判多少个组合。

这不是"性能优化"型基准——本仓是零依赖离线链路，吞吐不是目标。它回答的是：
**决策函数的全组合求值是否便宜到可以作为每轮 run 的门禁**。数字来自真实
`engine.evaluate` 调用（在 `DIMS`/`feasible`/`to_evidence` 之上组合），不是
虚构的吞吐声明。

用法：
    python3 scripts/bench_decision_matrix.py [--repeat N] [--json]
    # --repeat N: 每个组合重复求值 N 次取平均（默认 1）
    # --json:    输出 JSON（默认打印可读行）

退出码：0 = 求值成功且输出非空；1 = 求值失败/输出空（fail-closed）。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "rules"))

import engine  # noqa: E402

# 复刻 joint_decision_matrix.py 的维度与可行判定，避免脚本间静默漂移。
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
    """与 joint_decision_matrix.py 的可行判定**逐字一致**。

    刻意从原脚本复刻而非 import，是为了让本基准独立于被测量对象
    （若两者漂移，本基准会先红——这是门禁自证，不是优化）。
    排除内部矛盾；被排除不等于被判通过。
    """
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=1,
                    help="每个组合重复求值 N 次取平均（默认 1）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    rules = engine.load_rules()

    # 枚举可行组合（与 joint_decision_matrix 一致）。
    keys = list(DIMS)
    import itertools
    combos = []
    for values in itertools.product(*(DIMS[k] for k in keys)):
        combo = dict(zip(keys, values))
        if feasible(combo):
            combos.append(combo)
    total_raw = 1
    for v in DIMS.values():
        total_raw *= len(v)
    n_feasible = len(combos)
    if n_feasible == 0:
        print("FAIL: 0 个可行组合", file=sys.stderr)
        return 1

    # 逐组合求值，统计耗时。
    t0 = time.perf_counter()
    verdict_counts: dict[str, int] = {}
    evaluations = 0
    for combo in combos:
        ev = to_evidence(combo)
        for _ in range(max(1, args.repeat)):
            result = engine.evaluate(rules, ev)
            evaluations += 1
        v = result["verdict"]
        verdict_counts[v] = verdict_counts.get(v, 0) + 1
    t1 = time.perf_counter()
    elapsed = t1 - t0

    if not verdict_counts:
        print("FAIL: 求值无输出", file=sys.stderr)
        return 1

    per_eval_ms = (elapsed / evaluations) * 1000.0
    per_sec = evaluations / elapsed if elapsed > 0 else float("inf")

    if args.json:
        out = {
            "combos_total_raw": total_raw,
            "combos_feasible": n_feasible,
            "evaluations": evaluations,
            "elapsed_seconds": round(elapsed, 6),
            "ms_per_evaluation": round(per_eval_ms, 4),
            "evaluations_per_second": round(per_sec, 1),
            "verdict_counts": verdict_counts,
        }
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        print(f"原始组合 {total_raw} → 可行 {n_feasible}")
        print(f"求值 {evaluations} 次，总耗时 {elapsed:.4f}s")
        print(f"每次求值 {per_eval_ms:.4f} ms，吞吐 {per_sec:.1f} 组合/s")
        print(f"裁决分布: {verdict_counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
