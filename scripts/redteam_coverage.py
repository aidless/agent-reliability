#!/usr/bin/env python3
"""agent-redteam 剧本 → mcp-guard 工具面规则的覆盖率表（M4）。

读 `aidless/agent-redteam` 的 `data/attack_vectors.json`（12 向量 / 50 样本），
把每条 `payload` 过一遍 mcp-guard 的 `scan_text`，产出两张表：

    覆盖的   —— 这条攻击的载荷能被工具面规则表达（哪条规则、锚点是什么）
    不覆盖的 —— 明确标出来，不假装它被覆盖了

**这条覆盖率的准确含义（别读大）**：
mcp-guard 检查的是**工具定义**，不是用户输入。所以"覆盖"= 「同一段文本如果出现在
工具描述里，规则包会命中」，**不等于**运行时会拦住这条攻击——两者的位置不同。
本表回答的是提案里的那个问题：剧本产出的每条攻击，能不能被工具面规则**表达**。

用法：
    python3 scripts/redteam_coverage.py                     # 默认读 ~/agent-redteam
    python3 scripts/redteam_coverage.py --redteam-repo PATH --out reports/x.json
退出码：0 = 正常产出；2 = 数据文件不存在。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_REDTEAM = str(pathlib.Path.home() / "agent-redteam")
DEFAULT_GUARD = str(pathlib.Path.home() / "mcp-guard")


def git_commit(repo: pathlib.Path) -> str:
    try:
        out = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=30)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def load_vectors(redteam_repo: pathlib.Path) -> tuple[dict, list[dict]]:
    path = redteam_repo / "data" / "attack_vectors.json"
    if not path.exists():
        print(f"找不到 {path}", file=sys.stderr)
        raise SystemExit(2)
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("metadata", {}), data.get("attack_vectors", [])


def build_report(redteam_repo: pathlib.Path, guard_repo: pathlib.Path) -> dict:
    sys.path.insert(0, str(guard_repo))
    try:
        from guard.rules import scan_text
    except ImportError as e:
        print(f"无法从 {guard_repo} 导入 guard.rules: {e}", file=sys.stderr)
        raise SystemExit(2)

    metadata, vectors = load_vectors(redteam_repo)
    rows, by_vector = [], []
    for v in vectors:
        samples = v.get("samples", [])
        covered = 0
        for s in samples:
            payload = s.get("payload") or ""
            hits = scan_text(payload)
            if hits:
                covered += 1
            rows.append({
                "vector_id": v.get("vector_id"),
                "vector_name": v.get("name"),
                "category": v.get("category"),
                "sample_id": s.get("id"),
                "target_agent": s.get("target_agent"),
                "covered": bool(hits),
                "rules": [h["rule"] for h in hits],
                "anchors": [h["anchor"] for h in hits],
                "match": (hits[0]["match"] if hits else ""),
                "payload_len": len(payload),
            })
        by_vector.append({
            "vector_id": v.get("vector_id"),
            "vector_name": v.get("name"),
            "category": v.get("category"),
            "samples": len(samples),
            "covered": covered,
            "rate": round(covered / len(samples), 4) if samples else 0.0,
        })

    total = len(rows)
    covered_total = sum(1 for r in rows if r["covered"])
    return {
        "generated_utc": dt.datetime.now(dt.timezone.utc)
                                .isoformat(timespec="seconds"),
        # 不写本机绝对路径：commit 已足够溯源，公开产物里不该出现 checkout 路径
        "redteam_commit": git_commit(redteam_repo),
        "guard_commit": git_commit(guard_repo),
        "dataset_version": metadata.get("version"),
        "dataset_license": metadata.get("license"),
        "dataset_total_samples": metadata.get("total_samples"),
        "interpretation": (
            "覆盖 = 同一段文本若出现在工具描述里，规则包会命中；"
            "mcp-guard 检查工具定义，不检查用户输入，所以覆盖率不等于运行时拦截率。"
        ),
        "total_samples": total,
        "covered": covered_total,
        "uncovered": total - covered_total,
        "coverage_rate": round(covered_total / total, 4) if total else 0.0,
        "by_vector": by_vector,
        "samples": rows,
    }


def print_tables(report: dict) -> None:
    covered = [r for r in report["samples"] if r["covered"]]
    uncovered = [r for r in report["samples"] if not r["covered"]]

    print(f"agent-redteam @ {report['redteam_commit'][:12]}  "
          f"(dataset v{report['dataset_version']}, {report['total_samples']} 条)")
    print(f"mcp-guard     @ {report['guard_commit'][:12]}")
    print(f"覆盖率 {report['covered']}/{report['total_samples']} = "
          f"{report['coverage_rate']}\n")

    print("=== 表 1：覆盖（规则包能表达） ===")
    for r in covered:
        print(f"  {r['sample_id']:<10} {r['vector_name'] or '':<30} "
              f"{','.join(r['rules']):<20} anchor={','.join(r['anchors'])}")

    print("\n=== 表 2：不覆盖（明确标出，不假装覆盖） ===")
    for r in uncovered:
        print(f"  {r['sample_id']:<10} {r['vector_name'] or '':<30} "
              f"({r['payload_len']} 字符，未命中任何规则)")

    print("\n按向量：")
    for v in report["by_vector"]:
        print(f"  {v['vector_id']:<32} {v['covered']}/{v['samples']} = {v['rate']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--redteam-repo", default=DEFAULT_REDTEAM)
    ap.add_argument("--mcp-guard-repo", default=DEFAULT_GUARD)
    ap.add_argument("--out", default=None,
                    help="输出 JSON 路径（默认 reports/redteam-coverage-YYYYMMDD.json）")
    ap.add_argument("--quiet", action="store_true", help="只写文件，不打印表格")
    args = ap.parse_args()

    report = build_report(pathlib.Path(args.redteam_repo),
                          pathlib.Path(args.mcp_guard_repo))
    out = pathlib.Path(args.out) if args.out else (
        ROOT / "reports" /
        f"redteam-coverage-{dt.date.today().strftime('%Y%m%d')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.quiet:
        print_tables(report)
        print(f"\n写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
