#!/usr/bin/env python3
"""变异控制：故意破坏实现，确认测试真的会红。

门禁自证——如果把实现改坏测试仍然全绿，那这套测试就是装饰品。
每个变异都在一份临时拷贝上注入，跑完 unittest，然后丢弃拷贝。

用法：
    python3 scripts/mutation_control.py            # 全部变异
    python3 scripts/mutation_control.py --list     # 只列变异，不跑
退出码：0 = 每个变异都被测试抓到；1 = 有变异逃逸（测试没牙齿）。
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent

# (名称, 相对路径, 原文, 替换文)
MUTATIONS = [
    (
        "M1-ref-root-not-propagated",
        "contracts/jsonschema_mini.py",
        "    if root is None:\n        root = schema",
        "    if root is None:\n        root = {'broken': 1}",
    ),
    (
        "M1-schema-additional-properties-open",
        "contracts/run.schema.json",
        '"additionalProperties": false,\n  "properties": {\n    "run_id"',
        '"additionalProperties": true,\n  "properties": {\n    "run_id"',
    ),
    (
        "M1-schema-digest-pattern-loosened",
        "contracts/tool-evidence.schema.json",
        '"pattern": "^[0-9a-f]{64}$"',
        '"pattern": "^.*$"',
    ),
    (
        "M2-precedence-reversed",
        "rules/joint_verdict.json",
        '"verdict_precedence": ["BLOCK", "FAIL", "REVIEW", "INCOMPLETE", "PASS"]',
        '"verdict_precedence": ["PASS", "INCOMPLETE", "REVIEW", "FAIL", "BLOCK"]',
    ),
    (
        "M2-rule-r8-disabled",
        "rules/joint_verdict.json",
        '{"field": "missing_evidence_count", "op": "gt", "value": 0}',
        '{"field": "missing_evidence_count", "op": "gt", "value": 99}',
    ),
    (
        "M2-rule-r2-disabled",
        "rules/joint_verdict.json",
        '{"field": "tool_flagged", "op": "gt", "value": 0},\n        {"field": "audit_naive_all_green", "op": "eq", "value": true}',
        '{"field": "tool_flagged", "op": "gt", "value": 99},\n        {"field": "audit_naive_all_green", "op": "eq", "value": true}',
    ),
    (
        "M2-rule-r1-disabled",
        "rules/joint_verdict.json",
        '{"field": "tool_drift_alarm", "op": "gt", "value": 0}',
        '{"field": "tool_drift_alarm", "op": "gt", "value": 99}',
    ),
    (
        "M2-engine-alarm-ignores-payload-swap",
        "rules/engine.py",
        'if (t.get("drift") or {}).get("new_hits")\n            or (t.get("drift") or {}).get("changed_hits"))',
        'if (t.get("drift") or {}).get("new_hits"))',
    ),
    (
        "M2-engine-keeps-only-first-match",
        "rules/engine.py",
        "    if winner is None:",
        "    if len(matched) > 1:\n        matched = matched[:1]\n    if winner is None:",
    ),
    (
        "M2-engine-missing-evidence-dropped",
        "rules/engine.py",
        '        "missing_evidence": evidence.get("_missing_evidence", []),',
        '        "missing_evidence": [],',
    ),
]


def run_tests(proj_dir: pathlib.Path) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        capture_output=True, text=True, cwd=str(proj_dir))
    tail = (proc.stderr or proc.stdout).strip().splitlines()
    return proc.returncode, (tail[-1] if tail else "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="只列变异，不执行")
    args = ap.parse_args()

    if args.list:
        for name, path, _, _ in MUTATIONS:
            print(f"{name:<38} {path}")
        return 0

    # 先确认未变异时是绿的——否则"变异后变红"没有意义
    code, msg = run_tests(ROOT)
    print(f"[baseline]  {'PASS' if code == 0 else 'FAIL'}  {msg}")
    if code != 0:
        print("基线本身就没绿，先修基线再谈变异控制。")
        return 1

    escaped = []
    for name, rel, old, new in MUTATIONS:
        target = ROOT / rel
        original = target.read_text(encoding="utf-8")
        if old not in original:
            print(f"[{name:<38}] SKIP  锚点没找到（文件可能已改）：{rel}")
            escaped.append(name)
            continue
        with tempfile.TemporaryDirectory() as tmp:
            proj = pathlib.Path(tmp) / "proj"
            shutil.copytree(ROOT, proj)
            t = proj / rel
            t.write_text(original.replace(old, new, 1), encoding="utf-8")
            code, msg = run_tests(proj)
        caught = code != 0
        print(f"[{name:<38}] {'CAUGHT' if caught else 'ESCAPED'}  {msg}")
        if not caught:
            escaped.append(name)

    print()
    if escaped:
        print(f"逃逸 {len(escaped)} 个变异——这些实现没有测试兜底：{escaped}")
        return 1
    print(f"全部 {len(MUTATIONS)} 个变异都被测试抓到（测试有牙齿）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
