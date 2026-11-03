#!/usr/bin/env python3
"""轨迹完整性：把"答案对不对"和"过程能不能审计"拆成两个独立判据。

判据来自两篇研究（见 README「轨迹完整性」一节）：
  * Trace Integrity —— 过程是否显式、可执行、schema 合法、可复算、可审计。
  * CAIT（Correct Answer / Invalid Trace）—— 答案对、但支撑它的过程不存在。
    答案层满分 + 轨迹层无效 = CAIT，这一格是答案层看不见的盲区。

这个模块是纯函数：给 dataset / predictions / tools / trace，算出逐题轨迹与汇总。
它自己不判联合裁决（那是 rules/ 的事），也不写文件（那是调用方的事）。

两种轨迹来源，都记录在产物里，绝不混为一种证据：
  * `self`（离线自证）—— 没有真实工具调用记录时，把答案与已扫描的工具面连线：
    逐字面找答案里引用的工具名，能对上本轮 tools.json 的记为 grounds_claim。
    这只能证明"结论引用了本轮真实存在且 schema 合法的工具"，不能证明运行时真调过。
  * `external`（外部记录）—— 调用方给出真实 tool_calls，直接落盘。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "contracts"))

from jsonschema_mini import validate as _schema_validate  # noqa: E402

TRACE_VERSION = "1.0.0"


def _tool_schema(tool: dict) -> dict:
    return tool.get("inputSchema") or tool.get("parameters") or {}


def _answer_passed(item: dict, report_row: dict):
    """答案层是否满分：返回 True / False / None。

    None = 答案层没有可判定的结果（没有任何 exact check、或全是未知/软检查类型）。
    这与答案层"未知检查类型：跳过但记录"的处理一致——没被真正评过的题不能当成
    通过（否则 all() 会对空集合返回 True，把"没评"伪装成"满分"），也不能当成失败。

    特殊情况：上游 scorer 有一个已知 bug——如果题目里所有 check 类型都不在
    DISPATCH 表里，score 会被算成 0.0（而非 None），导致 R7 误判"未满分"。
    这里用「所有 exact check 的 passed 都是 None」来识别这种情况，优先于 score 字段。
    """
    if not report_row:
        return False
    exact = report_row.get("exact_checks") or {}
    if exact:
        # 如果全部 exact check 的 passed 都是 None（未知类型被记进 exact_checks），
        # 那么答案层实际上无法评判——返回 None，不是 False。
        passed_values = [(v or {}).get("passed") for v in exact.values()]
        if all(p is None for p in passed_values):
            return None
        # 有真实布尔值的 exact check：用它们判定
        bool_checks = [p for p in passed_values if isinstance(p, bool)]
        if bool_checks:
            return all(bool_checks)
    if "score" in report_row:
        score = report_row["score"]
        return None if score is None else float(score) >= 1.0
    return None


def _args_schema_errors(tool: dict, args: dict) -> list[str]:
    return _schema_validate(args, _tool_schema(tool))


def _self_trace_row(
    item: dict,
    report_row: dict,
    pred: dict,
    known: dict,
) -> dict:
    """离线自证：答案引用的工具名能否在已扫描的工具面里对上号。"""
    output = str(pred.get("output") or pred.get("answer") or "")
    tool_calls = []
    for name in sorted(known):
        if re.search(re.escape(name), output):
            tool = known[name]
            schema_errors = _args_schema_errors(tool, {})
            tool_calls.append({
                "tool": name,
                "args": {},
                "grounds_claim": True,
                "known_tool": True,
                "schema_valid": not schema_errors,
                "schema_errors": schema_errors,
            })
    # 抓"结论提到了工具、但本轮工具面里根本没有它"的孤儿引用。
    for m in re.finditer(r"\b([a-z][a-z0-9_.]*(?:_[a-z0-9_.]+)+)\b", output):
        cand = m.group(1)
        if cand in known:
            continue
        if any(tc["tool"] == cand for tc in tool_calls):
            continue
        # 词面像工具名（带下划线段），但工具面没有 → 孤儿，无法判 schema。
        tool_calls.append({
            "tool": cand,
            "args": {},
            "grounds_claim": False,
            "known_tool": False,
            "schema_valid": False,
            "schema_errors": ["unknown tool: 不在本轮扫描的工具面里"],
        })
    return _finish_row(item.get("id"), report_row, item, tool_calls)


def _external_trace_row(item: dict, report_row: dict, pred: dict, known: dict) -> dict:
    """外部记录：调用方提供真实 tool_calls，逐条判已知 / schema / 是否支撑结论。"""
    tool_calls = []
    # 只认真正的调用记录。run.py 的 agent 循环还会把最后的 assistant 文本消息
    # 存进 tool_calls（role=assistant），那不是工具调用——否则会造出 tool="?"
    # 的幽灵调用，把 schema_invalid 撑满。真正的调用有 "tool" 字段。
    for call in (pred.get("tool_calls") or []):
        if not isinstance(call, dict):
            continue
        if "tool" not in call and "name" not in call:
            continue  # assistant 文本消息 / 其它非调用条目
        name = call.get("tool") or call.get("name") or "?"
        tool = known.get(name)
        args = call.get("args") or call.get("arguments") or {}
        if not isinstance(args, dict):
            args = {"_raw": args}
        schema_errors = _args_schema_errors(tool, args) if tool else []
        tool_calls.append({
            "tool": name,
            "args": args,
            "grounds_claim": bool(call.get("grounds_claim", True)),
            "known_tool": tool is not None,
            "schema_valid": tool is not None and not schema_errors,
            "schema_errors": ([] if tool else ["unknown tool"]) + schema_errors,
        })
    return _finish_row(item.get("id"), report_row, item, tool_calls)


# 需要真实工具调用支撑结论的任务类型。不在此列的任务（纯推理/总结）默认
# 不需要工具链，既不是 CAIT 也不是 neutral——否则「不调工具」本身会被误判。
TOOL_TASKS = {"verifier_design", "eval_yaml", "reviewer_qa"}


def _requires_tools(item: dict) -> bool:
    """这题是否需要真实工具调用作为证据链。

    只有需要工具支撑结论的任务（verifier_design / eval_yaml 等）才纳入 CAIT；
    failure_diagnosis / report_summary 本就是纯推理任务，不调工具是正常的，
    把它们算成 CAIT 会是结构性误报。
    """
    declared = item.get("requires_tools")
    if declared is not None:
        return bool(declared)
    return item.get("task") in TOOL_TASKS


def _finish_row(item_id, report_row: dict, item: dict, tool_calls: list[dict]) -> dict:
    answer_passed = _answer_passed(item, report_row)
    grounded = [c for c in tool_calls
                if c["known_tool"] and c["schema_valid"] and c["grounds_claim"]]
    valid_trace = bool(grounded)
    requires = _requires_tools(item)
    # CAIT 只在答案层**确实满分**（answer_passed is True）且无可审计轨迹时成立。
    # answer_passed 为 None（答案层无法评判）时，不能把"没评"串成"CAIT"，
    # 必须显式标为 not_evaluated——否则 None 会通过 and 逻辑污染整个汇总。
    cait = (answer_passed is True) and requires and not valid_trace
    return {
        "id": item_id,
        "answer_passed": answer_passed,
        "answer_evaluated": answer_passed is not None,
        "tool_calls": tool_calls,
        "valid_trace": valid_trace,
        "requires_tools": requires,
        "neutral": requires and not valid_trace,
        "cait": bool(cait),
    }


def build_trace(
    dataset: list[dict],
    predictions: list[dict],
    tools: dict,
    report_rows: list[dict],
    source: str = "self",
    run_id: str | None = None,
) -> dict:
    """算出 trace.json 的内容。source ∈ {self, external}。

    有效来源由**实际数据**决定，而不是调用方怎么填：若预测里带了真实工具调用
    记录（tool_calls），那就是外部运行时证据，source 必须记作 external——把
    运行时调用记成 self（离线自证）会严重低估证据强度。
    """
    has_real_calls = any(
        isinstance(c, dict) and ("tool" in c or "name" in c)
        for p in predictions for c in (p.get("tool_calls") or []))
    effective_source = "external" if has_real_calls else source
    if isinstance(tools, dict):
        tool_list = tools.get("tools", [])
    else:
        tool_list = tools
    known = {t.get("name", "?"): t for t in tool_list}
    by_id = {p.get("id"): p for p in predictions}
    by_id_report = {r.get("id"): r for r in report_rows}

    items = []
    for item in dataset:
        iid = item.get("id")
        pred = by_id.get(iid) or {}
        report_row = by_id_report.get(iid) or {}
        if effective_source == "external" or pred.get("tool_calls"):
            items.append(_external_trace_row(item, report_row, pred, known))
        else:
            items.append(_self_trace_row(item, report_row, pred, known))

    cait = sum(1 for r in items if r["cait"])
    neutral = sum(1 for r in items if r.get("neutral"))  # 需要工具但轨迹不可审计
    orphans = sum(1 for r in items if r["tool_calls"] and not r["valid_trace"])
    schema_invalid = sum(
        1 for r in items
        if any(not c["schema_valid"] for c in r["tool_calls"]))
    answered = sum(1 for r in items if r.get("answer_evaluated"))
    out = {
        "trace_version": TRACE_VERSION,
        "source": effective_source,
        "requested_source": source,
        "trace_total": len(items),
        "trace_answered": answered,
        "trace_cait_count": cait,
        "trace_neutral": neutral,
        "trace_orphans": orphans,
        "trace_schema_invalid": schema_invalid,
        "items": items,
    }
    if run_id is not None:
        out["run_id"] = run_id
    return out


def load_jsonl(path: pathlib.Path) -> list[dict]:
    return [json.loads(x) for x in
            pathlib.Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--predictions", required=True)
    ap.add_argument("--tools", required=True)
    ap.add_argument("--report", required=True, help="audit/report.jsonl")
    ap.add_argument("--source", choices=["self", "external"], default="self")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    tools = json.loads(pathlib.Path(args.tools).read_text(encoding="utf-8"))
    if isinstance(tools, dict) and "tools" not in tools:
        tools = {"tools": tools if isinstance(tools, list) else [tools]}
    trace = build_trace(
        load_jsonl(args.dataset), load_jsonl(args.predictions), tools,
        load_jsonl(args.report), source=args.source)
    pathlib.Path(args.out).write_text(
        json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: trace[k] for k in
                      ("source", "trace_total", "trace_answered", "trace_cait_count",
                       "trace_orphans", "trace_schema_invalid")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
