#!/usr/bin/env python3
"""契约校验器：按 schema 检查一次 run 的三份产物，并重算联合裁决做比对。

用法：
    python3 contracts/validate.py runs/<run_id>
    python3 contracts/validate.py --all

它做四件事：
  1. `meta.json`         对 `contracts/run.schema.json`
  2. `tools.json`        对 `contracts/tool-evidence.schema.json`
  3. `joint_verdict.json` 对 `contracts/joint-verdict.schema.json`
     （可选：`redteam.json` 对 `contracts/redteam.schema.json`——没跑攻击剧本就没有）
  4. **重算**联合裁决并与文件里存的那份逐字段比对——手改过的裁决、或
     产物与裁决不同步，都会被抓出来。

退出码：0 = 全部通过；1 = 有问题（问题逐条打印在 stderr）。
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "rules"))

from jsonschema_mini import validate  # noqa: E402
import engine  # noqa: E402

# 读侧向后兼容：历史 run 落盘时轨迹层还不存在，重算会在 evidence 里补齐缺失的
# trace_* 字段，并额外写两个标记键说明「这是历史兼容、非手改」。比对时跳过这两个
# 标记键——否则为兼容而加的标记自己会变成新的「不一致」。
COMPAT_MARKER_KEYS = {"compat_trace_fields_added", "compat_note"}

# 文件名 -> (schema, 是否可选)
SCHEMAS = {
    "meta.json": ("run.schema.json", False),
    "tools.json": ("tool-evidence.schema.json", False),
    "joint_verdict.json": ("joint-verdict.schema.json", False),
    "redteam.json": ("redteam.schema.json", True),
    "trace.json": ("trace.schema.json", True),
    "ood.json": ("ood.schema.json", True),
}


def check_run(run_dir: pathlib.Path) -> list[str]:
    problems: list[str] = []
    run_dir = pathlib.Path(run_dir)

    for filename, (schema_name, optional) in SCHEMAS.items():
        path = run_dir / filename
        schema = json.loads((HERE / schema_name).read_text(encoding="utf-8"))
        if not path.exists():
            if not optional:
                problems.append(f"{run_dir.name}/{filename}: 文件不存在")
            continue
        try:
            instance = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            problems.append(f"{run_dir.name}/{filename}: JSON 解析失败 {e}")
            continue
        for err in validate(instance, schema):
            problems.append(f"{run_dir.name}/{filename}: {err}")

    # 4. 重算裁决并比对
    jv_path = run_dir / "joint_verdict.json"
    if jv_path.exists():
        try:
            stored = json.loads(jv_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            stored = {}
        stored_decision = stored.get("decision")
        if stored_decision is None:
            problems.append(f"{run_dir.name}/joint_verdict.json: 缺少 decision 字段（M2 之前的老产物）")
        else:
            recomputed = engine.decide(run_dir)
            for key in ("verdict", "severity", "rule_id", "missing_evidence"):
                if stored_decision.get(key) != recomputed.get(key):
                    problems.append(
                        f"{run_dir.name}/joint_verdict.json: decision.{key} 与重算结果不一致 "
                        f"(存储 {stored_decision.get(key)!r} vs 重算 {recomputed.get(key)!r})"
                    )
            if stored_decision.get("evidence") != recomputed.get("evidence"):
                # 只把「历史兼容标记键」从比对里豁免：重算比存储多的、且不在豁免表
                # 里的键，仍然算不一致（防止用兼容逻辑掩盖真正被删掉/改掉的字段）。
                stored_ev = stored_decision.get("evidence") or {}
                recomp_ev = recomputed.get("evidence") or {}
                exempt = {k: v for k, v in recomp_ev.items()
                          if k in COMPAT_MARKER_KEYS and k not in stored_ev}
                trimmed_stored = {k: v for k, v in stored_ev.items() if k not in COMPAT_MARKER_KEYS}
                trimmed_recomp = {k: v for k, v in recomp_ev.items() if k not in exempt}
                if trimmed_stored != trimmed_recomp:
                    problems.append(
                        f"{run_dir.name}/joint_verdict.json: decision.evidence 与重算结果不一致 "
                        f"(存储 {stored_decision.get('evidence')!r} vs 重算 {recomputed.get('evidence')!r})")

    return problems


def main() -> int:
    args = sys.argv[1:]
    runs_dir = ROOT / "runs"
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if args[0] == "--all":
        # "_" 前缀是历史归档（M2 之前的产物，没有 decision 字段），默认跳过。
        targets = sorted(p for p in runs_dir.iterdir() if p.is_dir() and not p.name.startswith("_"))
    else:
        targets = [pathlib.Path(a) for a in args]

    all_problems: list[str] = []
    for t in targets:
        if not t.is_dir():
            all_problems.append(f"{t}: 不是目录")
            continue
        problems = check_run(t)
        status = "OK" if not problems else f"FAIL ({len(problems)} 个问题)"
        print(f"{t.name:<28} {status}")
        all_problems.extend(problems)

    if all_problems:
        print("\n问题清单：", file=sys.stderr)
        for p in all_problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"\n全部通过（{len(targets)} 个 run）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
