"""联合裁决引擎：证据 → 结论。

规则在 `rules/joint_verdict.json` 里（数据），这里只负责求值。
改判据请改 JSON，不要改这个文件。

两处刻意的设计：
1. **全部规则都求值**，命中的规则全部记进 `matched_rules`；最终 verdict 按
   `verdict_precedence` 取最严重的那一个。这样"为什么不是 PASS"能被追溯，
   而不是只看到一个结论。
2. **缺证据 ≠ 通过**。缺层时命中 R8 → INCOMPLETE，与 PASS 严格区分。
"""
from __future__ import annotations

import json
import pathlib

RULES_PATH = pathlib.Path(__file__).resolve().parent / "joint_verdict.json"


def load_rules(path: pathlib.Path | str = RULES_PATH) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def derive_evidence(run_dir: pathlib.Path, rules: dict | None = None) -> dict:
    """从一次 run 的产物目录里推出归一化的证据字段。"""
    rules = rules or load_rules()
    run_dir = pathlib.Path(run_dir)

    evidence = {
        "tool_scanned": 0,
        "tool_flagged": 0,
        "tool_flagged_names": [],
        "tool_drift_alerts": 0,
        "tool_drift_new_hits": 0,
        "tool_drift_changed_hits": 0,
        "tool_drift_alarm": 0,
        "tool_drift_unknown": 0,
        "tool_clean": True,
        "audit_present": False,
        "audit_total": 0,
        "audit_semantic_scored": 0,
        "audit_excluded": 0,
        "audit_runtime_errors": 0,
        "audit_rate": None,
        "audit_rate_is_1": False,
        "audit_naive_all_green": None,
        "audit_naive_green": "",
        "audit_unsupported_claims": 0,
        "missing_evidence_count": 0,
        "output_evidence_regressed": False,
        "attack_sim_present": False,
        "attack_samples": 0,
        "attack_covered": 0,
        "attack_uncovered": 0,
    }
    missing: list[str] = []

    # ---- L1 输入面 ----
    tools_path = run_dir / "tools.json"
    if tools_path.exists():
        tools = json.loads(tools_path.read_text(encoding="utf-8"))
        evidence["tool_scanned"] = tools.get("scanned", len(tools.get("tools", [])))
        flagged = [t for t in tools.get("tools", []) if t.get("flagged")]
        evidence["tool_flagged"] = len(flagged)
        evidence["tool_flagged_names"] = [t["name"] for t in flagged]
        drifts = [t for t in tools.get("tools", [])
                  if (t.get("drift") or {}).get("status") in ("DRIFT", "changed")]
        evidence["tool_drift_alerts"] = len(drifts)
        # 三个计数分开报，因为它们回答不同问题：
        #   new_hits     = 有全新规则开始触发
        #   changed_hits = 同一规则，但命中的东西被换掉了（载荷替换）
        #   alarm        = 上面任一为真；None 表示"没快照，无法判断"
        evidence["tool_drift_new_hits"] = sum(
            1 for t in drifts if (t.get("drift") or {}).get("new_hits"))
        evidence["tool_drift_changed_hits"] = sum(
            1 for t in drifts if (t.get("drift") or {}).get("changed_hits"))
        # alarm 由原始数据推出来，而不是直接读产物里的 alarm 字段——
        # 这样即使上游没写 alarm，平台也不会把"有变化"误读成"没变化"。
        evidence["tool_drift_alarm"] = sum(
            1 for t in drifts
            if (t.get("drift") or {}).get("new_hits")
            or (t.get("drift") or {}).get("changed_hits"))
        evidence["tool_drift_unknown"] = sum(
            1 for t in drifts if t.get("drift") and t["drift"].get("alarm") is None)
    else:
        missing.append("input_guard")

    # ---- L3 输出面 ----
    summary_path = run_dir / "audit" / "summary.json"
    naive_path = run_dir / "audit" / "naive_verdicts.jsonl"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        evidence["audit_present"] = True
        evidence["audit_total"] = summary.get("total", 0)
        evidence["audit_semantic_scored"] = summary.get("semantic_scored", 0)
        evidence["audit_excluded"] = evidence["audit_total"] - evidence["audit_semantic_scored"]
        evidence["audit_runtime_errors"] = summary.get("runtime_errors", 0)
        rate = summary.get("overall_reference_check_rate")
        evidence["audit_rate"] = rate
        evidence["audit_rate_is_1"] = (rate is not None and abs(rate - 1.0) < 1e-9)
        evidence["audit_unsupported_claims"] = summary.get("items_with_unsupported_claims", 0)
        if naive_path.exists():
            rows = [json.loads(l) for l in naive_path.read_text(encoding="utf-8").splitlines() if l.strip()]
            green = sum(1 for r in rows if r.get("verdict") == "pass")
            evidence["audit_naive_green"] = f"{green}/{len(rows)}"
            evidence["audit_naive_all_green"] = bool(rows) and green == len(rows)
    else:
        missing.append("output_audit")

    # ---- L2（可选）：攻击剧本覆盖 ----
    redteam_path = run_dir / "redteam.json"
    if redteam_path.exists():
        redteam = json.loads(redteam_path.read_text(encoding="utf-8"))
        evidence["attack_sim_present"] = True
        evidence["attack_samples"] = redteam.get("total_samples", 0)
        evidence["attack_covered"] = redteam.get("covered", 0)
        evidence["attack_uncovered"] = redteam.get("uncovered", 0)

    # ---- 必需层 / 可选层 ----
    required = rules.get("required_layers", ["input_guard", "output_audit"])
    missing = [m for m in missing if m in required]
    evidence["missing_evidence_count"] = len(missing)

    # 证据回退：上一轮有输出面、这一轮没有 —— 不是"没跑"，是证据消失了。
    # 删掉 audit/ 会连带消掉依赖它的判据（例如 R2 的假绿 BLOCK），
    # 所以"消失"本身必须是一个独立信号，否则门禁可以被删文件绕过。
    if "output_audit" in missing and tools_path.exists():
        baseline_run = (json.loads(tools_path.read_text(encoding="utf-8"))
                        .get("baseline_run"))
        if baseline_run:
            baseline_summary = run_dir.parent / baseline_run / "audit" / "summary.json"
            evidence["output_evidence_regressed"] = baseline_summary.exists()

    evidence["tool_clean"] = (evidence["tool_flagged"] == 0 and evidence["tool_drift_alerts"] == 0)
    evidence["_missing_evidence"] = missing
    return evidence


def _resolve(evidence: dict, field: str):
    node = evidence
    for part in field.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _condition_holds(cond: dict, evidence: dict) -> bool:
    actual = _resolve(evidence, cond["field"])
    op = cond.get("op", "eq")
    expected = cond.get("value")
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if op == "gt":
        return isinstance(actual, (int, float)) and not isinstance(actual, bool) and actual > expected
    if op == "gte":
        return isinstance(actual, (int, float)) and not isinstance(actual, bool) and actual >= expected
    if op == "lt":
        return isinstance(actual, (int, float)) and not isinstance(actual, bool) and actual < expected
    if op == "lte":
        return isinstance(actual, (int, float)) and not isinstance(actual, bool) and actual <= expected
    if op == "nonempty":
        return bool(actual)
    if op == "empty":
        return not actual
    if op == "in":
        return actual in expected
    if op == "contains":
        return isinstance(actual, (list, str)) and expected in actual
    raise ValueError(f"未知操作符 {op!r}")


def evaluate(rules: dict, evidence: dict) -> dict:
    """按规则求值，返回联合裁决。"""
    matched = []
    for rule in rules["rules"]:
        conditions = rule.get("all", [])
        if all(_condition_holds(c, evidence) for c in conditions):
            matched.append({
                "id": rule["id"],
                "verdict": rule["verdict"],
                "severity": rule["severity"],
                "why": rule["why"],
            })

    precedence = rules.get("verdict_precedence", ["BLOCK", "FAIL", "REVIEW", "INCOMPLETE", "PASS"])
    winner = None
    for verdict in precedence:
        for m in matched:
            if m["verdict"] == verdict:
                winner = m
                break
        if winner:
            break

    if winner is None:
        winner = {"id": None, "verdict": rules.get("default_verdict", "PASS"),
                  "severity": rules.get("default_severity", "info"),
                  "why": "没有任何规则命中：工具面干净，输出面权威评分满分。"}

    public_evidence = {k: v for k, v in evidence.items() if not k.startswith("_")}
    return {
        "verdict": winner["verdict"],
        "severity": winner["severity"],
        "rule_id": winner["id"],
        "why": winner["why"],
        "matched_rules": matched,
        "evidence": public_evidence,
        "missing_evidence": evidence.get("_missing_evidence", []),
    }


def decide(run_dir: pathlib.Path, rules_path: pathlib.Path | str = RULES_PATH) -> dict:
    """从一次 run 的产物目录直接得出联合裁决。"""
    rules = load_rules(rules_path)
    evidence = derive_evidence(pathlib.Path(run_dir), rules)
    return evaluate(rules, evidence)
