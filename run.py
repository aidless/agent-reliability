#!/usr/bin/env python3
"""run.py — Agent Reliability Platform 的最小编排骨架（把两仓接在一起）。

它做三件事，一次跑完，产物落在 `runs/<run_id>/`：

  L1 输入面（mcp-guard）   工具定义 → 规则命中 + 哈希钉选 + 与上一次的漂移
  L3 输出面（auditable）   模型输出 → 权威 reference_check 评分 + naive 对照
  联合判决                 naive 全绿 / 工具被 flag / 权威评分 三者放在一起看

设计约束（来自两个仓自己的诚实性约束）：
  * 全离线、零模型调用、零 API key。
  * 任何数字都能用同一条命令复算。
  * 工具面"被 flag"不等于"判定为恶意"，只表示"值得人工看"——与 mcp-guard README 一致。

用法：
    python3 run.py --tools config/tools.example.json
    python3 run.py --tools config/tools.example.json \
                   --dataset config/joint_eval_dataset.jsonl \
                   --predictions config/joint_eval_predictions.jsonl

环境变量（可换成别的 checkout）：
    MCP_GUARD_REPO   默认 ~/mcp-guard
    AUDITABLE_REPO   默认 ~/auditable-llm-eval
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
# 默认值按 ~ 展开，不写死某台机器的绝对路径——CI 与别的读者都能直接用。
DEFAULT_MCP_GUARD = os.environ.get(
    "MCP_GUARD_REPO", os.path.expanduser("~/mcp-guard"))
DEFAULT_AUDITABLE = os.environ.get(
    "AUDITABLE_REPO", os.path.expanduser("~/auditable-llm-eval"))
sys.path.insert(0, str(ROOT / "rules"))

# naive 检查器策略：与 auditable-llm-eval 的 eval/run_copilot_eval.py 完全一致
# （非空 + 长度 >= 20），即"只看有没有吐字"的假绿检查器。
NAIVE_MIN_LEN = 20


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_version(path: pathlib.Path) -> str:
    """文件内容 sha256 前 16 位；文件不存在时返回 unknown（不猜）。"""
    p = pathlib.Path(path)
    return sha256_file(p)[:16] if p.exists() else "unknown"


def git_commit(repo: pathlib.Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def load_json(path: pathlib.Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path: pathlib.Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def naive_verdict(text: str) -> dict:
    """假绿检查器：只看非空 + 长度。与仓库里的策略逐字一致。"""
    t = (text or "").strip()
    ok = bool(t) and len(t) >= NAIVE_MIN_LEN
    return {"verdict": "pass" if ok else "fail", "len": len(t)}


def check_dataset_conformance(items: list[dict]) -> list[str]:
    """按 specs/test_50.schema.json 的关键约束做一次轻量自查（不引入 jsonschema 依赖）。"""
    import re

    allowed_tasks = {"eval_yaml", "failure_diagnosis", "report_summary",
                     "reviewer_qa", "verifier_design"}
    allowed_checks = {
        "must_include_any_keywords", "must_include_all_keywords", "must_answer_no",
        "must_explain_surface_constraints", "must_recommend_manual_or_semantic_eval",
        "must_mention_rerun_or_reproducibility", "must_not_claim_tamper_proof",
        "must_distinguish_provider_error", "must_not_judge_semantic_quality",
        "must_check_reason_and_action",
    }
    problems = []
    for it in items:
        for key in ("id", "task", "prompt", "reference_checks"):
            if key not in it:
                problems.append(f"{it.get('id', '?')}: missing field {key}")
        if not re.match(r"^c[0-9]{3}$", str(it.get("id", ""))):
            problems.append(f"{it.get('id')}: id 不符合 ^c[0-9]{{3}}$")
        if it.get("task") not in allowed_tasks:
            problems.append(f"{it.get('id')}: task 不在 schema 枚举内")
        if len(str(it.get("prompt", ""))) < 10:
            problems.append(f"{it.get('id')}: prompt 少于 10 字符")
        for c in it.get("reference_checks", []):
            if c.get("type") not in allowed_checks:
                problems.append(f"{it.get('id')}: 未知 check type {c.get('type')}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tools", required=True, help="MCP 工具定义 JSON")
    ap.add_argument("--dataset", default=None, help="评测集 jsonl（含 reference_checks）")
    ap.add_argument("--predictions", default=None, help="模型输出 jsonl")
    ap.add_argument("--predictions-model", default=None,
                    help="产出该预测的模型 id（写进 meta；不给就是 hand-written）")
    ap.add_argument("--run-id", default=None, help="本次 run 的 id（默认用时间戳）")
    ap.add_argument("--baseline-run", default=None,
                    help="显式指定漂移基线 run id（默认取 created_utc 最新的那次）")
    ap.add_argument("--no-baseline", action="store_true",
                    help="不做漂移比对（重建链首的 run 时用）")
    ap.add_argument("--redteam-repo", default=None,
                    help="aidless/agent-redteam 的 checkout（给了才跑攻击剧本覆盖表）")
    ap.add_argument("--mcp-guard-repo", default=DEFAULT_MCP_GUARD)
    ap.add_argument("--auditable-repo", default=DEFAULT_AUDITABLE)
    args_ = ap.parse_args()

    mcp_repo = pathlib.Path(args_.mcp_guard_repo).resolve()
    aud_repo = pathlib.Path(args_.auditable_repo).resolve()
    sys.path.insert(0, str(mcp_repo))
    sys.path.insert(0, str(aud_repo))

    from guard.scan import check_drift, digest_tool, scan_tool  # noqa: E402
    from copilot.score_copilot_run_v2 import run as score_run  # noqa: E402

    run_id = args_.run_id or dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = ROOT / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # ---------- L1 输入面：扫描 + 钉选 + 漂移 ----------
    tools = load_json(pathlib.Path(args_.tools))
    if isinstance(tools, dict):
        tools = tools.get("tools", [tools])

    # 与上一次 run 的钉选快照比对（字段级漂移）。
    # 基线按 created_utc 取**最新**的那次，而不是按目录名排序——
    # 否则一个叫 "tmp/" 或 "manual-check/" 的目录会悄悄变成基线，
    # 让漂移结论取决于目录名的字典序，而不是取决于实际跑过什么。
    def _created_utc(path: pathlib.Path) -> str:
        try:
            meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        return meta.get("created_utc", "")

    if args_.no_baseline:
        previous = []
    elif args_.baseline_run:
        # 显式基线：重建一条 run 链时用它，结论就不取决于目录里还有什么。
        pinned_run = ROOT / "runs" / args_.baseline_run
        if not (pinned_run / "tools.json").exists():
            ap.error(f"--baseline-run {args_.baseline_run!r} 不存在，或没有 tools.json")
        previous = [pinned_run]
    else:
        previous = sorted(
            (p for p in (ROOT / "runs").iterdir()
             if p.is_dir() and p.name != run_id
             and not p.name.startswith("_")      # "_" 前缀 = 历史归档，不参与基线
             and (p / "tools.json").exists()),
            key=lambda p: (_created_utc(p), p.name),
        )
    pinned, snapshots = {}, {}
    if previous:
        prev = load_json(previous[-1] / "tools.json")
        pinned = {t["name"]: t["digest"] for t in prev.get("tools", [])}
        snapshots = {t["name"]: t["definition"] for t in prev.get("tools", [])}

    rows, flagged = [], 0
    for t in tools:
        result = scan_tool(t)
        if result["flagged"]:
            flagged += 1
        digest = digest_tool(t)
        drift = check_drift(t, pinned, snapshots) if pinned else {
            "name": t.get("name", "?"), "status": "no-baseline",
            "digest": digest[:12], "fields": [], "new_hits": [],
            "changed_hits": [], "hit_delta": [], "alarm": None,
        }
        rows.append({
            "name": t.get("name", "?"),
            "digest": digest,
            "flagged": result["flagged"],
            "hits": result["hits"],
            "drift": drift,
            "definition": t,
        })

    rules_version = sha256_file(mcp_repo / "guard" / "rules.py")[:16]
    (run_dir / "tools.json").write_text(
        json.dumps({
            "run_id": run_id,
            "rules_version": rules_version,
            "scanned": len(tools),
            "flagged": flagged,
            "baseline_run": previous[-1].name if previous else None,
            "tools": rows,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    meta = {
        "run_id": run_id,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "rules_version": rules_version,
        # 评分器也有自己的版本：否则"模型变了"和"判分标准变了"永远分不开。
        "scorer_version": file_version(aud_repo / "copilot" / "score_copilot_run_v2.py"),
        "tool_digests": {r["name"]: r["digest"] for r in rows},
        "repos": {
            "mcp-guard": {"path": str(mcp_repo), "commit": git_commit(mcp_repo)},
            "auditable-llm-eval": {"path": str(aud_repo), "commit": git_commit(aud_repo)},
        },
        "tools_input": str(pathlib.Path(args_.tools).resolve()),
        # 输出面是谁产的：手写还是某个真实模型。不记这个，"模型变了"和
        # "判分标准变了"仍然分不开——scorer_version 只覆盖评分器那一侧。
        "predictions_model": args_.predictions_model or (
            "hand-written" if args_.predictions else None),
    }
    (run_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- L2（可选）：攻击剧本覆盖 ----------
    if args_.redteam_repo:
        sys.path.insert(0, str(ROOT / "scripts"))
        from redteam_coverage import build_report  # noqa: E402

        coverage = build_report(pathlib.Path(args_.redteam_repo), mcp_repo)
        (run_dir / "redteam.json").write_text(
            json.dumps({
                "run_id": run_id,
                "redteam_commit": coverage["redteam_commit"],
                "dataset_version": coverage["dataset_version"],
                "dataset_license": coverage["dataset_license"],
                "total_samples": coverage["total_samples"],
                "covered": coverage["covered"],
                "uncovered": coverage["uncovered"],
                "coverage_rate": coverage["coverage_rate"],
                "interpretation": coverage["interpretation"],
                "by_vector": coverage["by_vector"],
                # 只留判定所需字段：不把上游 Apache-2.0 的载荷复制进本仓
                "samples": [
                    {k: s[k] for k in
                     ("sample_id", "vector_id", "covered", "rules", "anchors")}
                    for s in coverage["samples"]
                ],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    joint = {
        "run_id": run_id,
        "input_guard": {
            "scanned": len(tools),
            "flagged": flagged,
            "flagged_tools": [r["name"] for r in rows if r["flagged"]],
            "drift_alerts": [
                {"name": r["name"], "status": r["drift"]["status"], "new_hits": r["drift"].get("new_hits", [])}
                for r in rows if r["drift"]["status"] in ("DRIFT", "changed")
            ],
            "verdict": "FLAG" if flagged else "CLEAN",
            "note": "flagged = 需要人工看，不等于判定为恶意（mcp-guard 的诚实性约束）",
        },
    }

    # ---------- L3 输出面：权威评分 + naive 对照 ----------
    if args_.predictions:
        if not args_.dataset:
            ap.error("--predictions 需要同时给 --dataset")
        dataset = pathlib.Path(args_.dataset)
        preds = pathlib.Path(args_.predictions)
        items = load_jsonl(dataset)
        predictions = load_jsonl(preds)

        conformance = check_dataset_conformance(items)
        audit_dir = run_dir / "audit"
        audit_dir.mkdir(exist_ok=True)
        results, summary = score_run(
            str(dataset), str(preds),
            str(audit_dir / "report.jsonl"),
            str(audit_dir / "summary.json"),
        )

        by_id = {p.get("id"): p for p in predictions}
        naive_rows, green = [], 0
        for it in items:
            p = by_id.get(it.get("id"), {})
            text = p.get("output") or p.get("answer") or p.get("prediction") or ""
            v = naive_verdict(text)
            if v["verdict"] == "pass":
                green += 1
            naive_rows.append({"id": it.get("id"), **v})
        (audit_dir / "naive_verdicts.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in naive_rows) + "\n",
            encoding="utf-8")

        rate = summary.get("overall_reference_check_rate")
        joint["output_audit"] = {
            "total": summary["total"],
            "semantic_scored": summary["semantic_scored"],
            "runtime_errors": summary["runtime_errors"],
            "authoritative_rate": rate,
            "naive_green": f"{green}/{len(items)}",
            "deception_gap_points": (round((1 - rate) * 100, 1) if rate is not None else None),
            "items_with_unsupported_claims": summary["items_with_unsupported_claims"],
            "dataset_conformance_problems": conformance,
            "verdict": "FAIL" if (rate is not None and rate < 1.0) else "PASS",
        }
        joint["joint_verdict"] = {
            "naive_green": f"{green}/{len(items)}",
            "input_guard": joint["input_guard"]["verdict"],
            "output_audit": joint["output_audit"]["verdict"],
            "headline": (
                f"naive 检查器 {green}/{len(items)} 全绿，但工具面 "
                f"{joint['input_guard']['verdict']}、权威评分 {rate}"
                if green == len(items) and rate is not None and rate < 1.0
                else "见各层字段"
            ),
        }

    # ---- M2：联合裁决（规则在 rules/joint_verdict.json，这里只调用）----
    import engine

    decision = engine.decide(run_dir)
    decision["rules_version"] = rules_version
    joint["decision"] = decision

    (run_dir / "joint_verdict.json").write_text(
        json.dumps(joint, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(joint, ensure_ascii=False, indent=2))
    print(f"\n产物写入：{run_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
