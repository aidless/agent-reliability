#!/usr/bin/env python3
"""用真实模型跑指定 JSONL 数据集，产出可送进 run.py 的预测。

为什么需要这个：在此之前 `config/joint_eval_predictions.jsonl` 的 3 条输出是**手写的**，
所以"auditable 抓假绿"只在构造数据上成立。这个脚本让它变成真实模型的产出。

凭据：走本机已配置的 OpenAI 兼容网关（默认 127.0.0.1:3425），**不读也不打印任何 key**。
产物里只记录模型 id 与用量，不记录网关地址。

用法：
    python3 scripts/run_real_model_eval.py --model raccoon/sn-deepseek-v4-1-flash
    python3 scripts/run_real_model_eval.py --model raccoon/sn-deepseek-v4-1-flash \
      --dataset config/induced_overclaim_dataset.jsonl
    python3 scripts/run_real_model_eval.py --model trae-cn/glm-5.3-flash-max
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_GATEWAY = "http://127.0.0.1:3425/v1"


def slug(model: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")


def default_output_path(root: pathlib.Path, dataset: pathlib.Path,
                        model: str) -> pathlib.Path:
    """把预测放在数据集旁，并让文件名携带数据集身份，避免实验互相覆盖。"""
    stem = dataset.stem
    if stem.endswith("_dataset"):
        stem = stem[:-len("_dataset")] + "_predictions"
    else:
        stem += "_predictions"
    return root / "config" / f"{stem}.real-{slug(model)}.jsonl"


def resolve_output_path(root: pathlib.Path, dataset: pathlib.Path,
                        model: str, explicit: pathlib.Path | None) -> pathlib.Path:
    return explicit if explicit is not None else default_output_path(root, dataset, model)


def call(gateway: str, model: str, prompt: str,
         max_tokens: int, timeout: int) -> dict:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        gateway.rstrip("/") + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = json.load(r)
    return {
        "content": payload["choices"][0]["message"].get("content") or "",
        "latency_ms": int((time.time() - t0) * 1000),
        "usage": payload.get("usage") or {},
        "served_model": payload.get("model"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--dataset", type=pathlib.Path,
                    default=ROOT / "config" / "joint_eval_dataset.jsonl")
    ap.add_argument("--output", type=pathlib.Path, default=None,
                    help="预测 JSONL 路径；默认按数据集名自动生成，避免覆盖别的实验")
    ap.add_argument("--gateway", default=DEFAULT_GATEWAY)
    ap.add_argument("--max-tokens", type=int, default=1200)
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()

    dataset = args.dataset.resolve()
    items = [json.loads(l) for l in
             dataset.read_text(encoding="utf-8").splitlines() if l.strip()]

    out_rows, failures = [], []
    for item in items:
        try:
            r = call(args.gateway, args.model, item["prompt"],
                     args.max_tokens, args.timeout)
        except urllib.error.HTTPError as e:
            failures.append({"id": item["id"], "error": f"HTTP {e.code}",
                             "body": e.read().decode(errors="replace")[:300]})
            continue
        except Exception as e:
            failures.append({"id": item["id"], "error": f"{type(e).__name__}: {e}"})
            continue
        out_rows.append({
            "id": item["id"],
            "output": r["content"],
            "model": args.model,
            "served_model": r["served_model"],
            "latency_ms": r["latency_ms"],
            "usage": r["usage"],
        })
        print(f"[{item['id']}] {len(r['content'])} 字符 / {r['latency_ms']}ms",
              file=sys.stderr)

    if failures:
        print(f"失败 {len(failures)} 条：{failures}", file=sys.stderr)
        return 1

    out = resolve_output_path(ROOT, dataset, args.model, args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out_rows) + "\n",
                   encoding="utf-8")
    meta = {
        "model": args.model,
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "temperature": 0,
        "max_tokens": args.max_tokens,
        "count": len(out_rows),
        "dataset_file": str(dataset),
        "predictions_file": out.name,
    }
    out.with_suffix(".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n写入 {out.name}（{len(out_rows)} 条，模型 {args.model}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
