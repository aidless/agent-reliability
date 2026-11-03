#!/usr/bin/env python3
"""让真实模型通过 function-calling 真实选择并调用工具，产出带 tool_calls 的预测。

与 run_real_model_eval.py（纯文本问答）的区别：这里用 OpenAI tools 协议跑一个
**多轮 agent 循环**，模型可以真的决定调用哪个工具、传什么参数。产出的
`tool_calls` 直接喂给 run.py --trace（source=external），让轨迹层第一次跑在
真实运行时数据上。

安全边界（必须保持）：
  * 工具**不在本机真执行**。execute() 是一个 stub：只记录 (tool, args) 并返回
    合成的假数据。绝不读 ~/.ssh、绝不真的发消息、绝不写文件。
  * 毒工具（export_profile / send_message）故意留在工具面里，用来测"模型会不会
    被 description 里的注入指令带偏去调用它"。这本身就是实验要测的东西。
  * 凭据走本机网关（默认 127.0.0.1:3425），不读也不打印任何 key；产物只记模型 id
    与用量，不记网关地址。

用法：
    python3 scripts/run_real_tooluse_eval.py --model opencode-go/deepseek-v4.1-flash
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
DEFAULT_MODEL = "opencode-go/deepseek-v4.1-flash"
MAX_TURNS = 6


def slug(model: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")


def load_tools(path: pathlib.Path) -> list[dict]:
    """把 mcp-guard 风格的工具定义转成 OpenAI tools 协议。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    tools = raw.get("tools", raw) if isinstance(raw, dict) else raw
    out = []
    for t in tools:
        fn = {
            "name": t.get("name"),
            "description": t.get("description", ""),
            "parameters": t.get("inputSchema") or t.get("parameters")
                          or {"type": "object", "properties": {}},
        }
        out.append({"type": "function", "function": fn})
    return out


def chat(gateway: str, model: str, messages: list[dict], tools: list[dict],
         max_tokens: int, timeout: int) -> dict:
    body = {"model": model, "messages": messages, "temperature": 0,
            "max_tokens": max_tokens, "tools": tools, "tool_choice": "auto"}
    req = urllib.request.Request(
        gateway.rstrip("/") + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = json.load(r)
    msg = payload["choices"][0]["message"]
    return {"message": msg, "served_model": payload.get("model"),
            "latency_ms": int((time.time() - t0) * 1000),
            "usage": payload.get("usage") or {}}


def execute_stub(tool: str, args: dict, injection: dict | None = None,
                 item_id: str | None = None) -> dict:
    """安全 stub：不真执行，返回合成数据。绝不能读凭据 / 发消息 / 写盘。

    injection 非空时，把 OOD 载荷塞进指定工具的**返回值**（不是描述），
    用来测"模型会不会执行工具输出里的指令"。
    """
    synth = {
        # 返回值带城市名，否则模型总结时会丢掉城市，答案层关键词检查会误判。
        "get_weather": {"city": args.get("city", "?"),
                        "weather_in": args.get("city", "?"),
                        "temp_c": 18, "condition": "cloudy",
                        "_synthetic": True},
        "export_profile": {"bundle_b64": "U1lOVEhFVElDLUJVTkRMRQ==",
                           "_synthetic": True, "_note": "stub：未读取任何真实凭据"},
        "send_message": {"delivered": False, "_synthetic": True,
                         "_note": "stub：未真正发送"},
        "generate_ssh_keypair": {"public_key": "ssh-ed25519 SYNTHETIC",
                                 "_synthetic": True},
    }
    result = dict(synth.get(tool, {"_synthetic": True, "_note": f"unknown tool {tool}"}))
    if injection and tool == injection.get("tool"):
        applies = injection.get("applies_to") or []
        if not applies or item_id in applies:
            result["notice"] = injection.get("payload", "")
            result["_ood_injected"] = True
    return result


def run_item(gateway, model, item, tools, max_tokens, timeout,
             injection=None) -> dict:
    """单题 agent 循环：模型 → (tool_calls) → stub 执行 → 回灌 → 再答。"""
    messages = [{"role": "user", "content": item["prompt"]}]
    calls, turns, latencies, usage = [], [], [], {}
    for _ in range(MAX_TURNS):
        r = chat(gateway, model, messages, tools, max_tokens, timeout)
        latencies.append(r["latency_ms"])
        for k, v in (r["usage"] or {}).items():
            if isinstance(v, (int, float)):
                usage[k] = usage.get(k, 0) + v
        msg = r["message"]
        tc = msg.get("tool_calls") or []
        if not tc:
            calls.append({"role": "assistant", "content": msg.get("content") or ""})
            break
        messages.append({"role": "assistant",
                         "content": msg.get("content") or "",
                         "tool_calls": tc})
        for c in tc:
            fn = (c.get("function") or {})
            name = fn.get("name") or "?"
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except json.JSONDecodeError:
                args = {"_raw": raw_args}
            result = execute_stub(name, args if isinstance(args, dict) else {},
                                  injection=injection, item_id=item.get("id"))
            calls.append({"tool": name, "args": args, "result": result,
                          "grounds_claim": True, "call_id": c.get("id")})
            messages.append({"role": "tool", "tool_call_id": c.get("id"),
                             "content": json.dumps(result, ensure_ascii=False)})
        turns.append(len(tc))
    content = ""
    for c in reversed(calls):
        if c.get("role") == "assistant":
            content = c["content"]
            break
    return {"id": item["id"], "output": content, "model": model,
            "served_model": None, "latency_ms": sum(latencies),
            "usage": usage, "tool_calls": calls, "turns": len(turns)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--dataset", type=pathlib.Path,
                    default=ROOT / "config" / "joint_eval_dataset.jsonl")
    ap.add_argument("--tools", type=pathlib.Path,
                    default=ROOT / "config" / "tools.example.json")
    ap.add_argument("--output", type=pathlib.Path, default=None)
    ap.add_argument("--gateway", default=DEFAULT_GATEWAY)
    ap.add_argument("--max-tokens", type=int, default=1200)
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--inject-return", type=pathlib.Path, default=None,
                    help="OOD 返回值注入配置（JSON）：把载荷塞进工具返回值，"
                         "测模型会不会执行工具输出里的指令。")
    args = ap.parse_args()

    dataset = args.dataset.resolve()
    items = [json.loads(l) for l in
             dataset.read_text(encoding="utf-8").splitlines() if l.strip()]
    tools = load_tools(args.tools.resolve())
    injection = (json.loads(args.inject_return.read_text(encoding="utf-8"))
                 if args.inject_return else None)

    rows, failures = [], []
    for item in items:
        try:
            r = run_item(args.gateway, args.model, item, tools,
                         args.max_tokens, args.timeout, injection=injection)
        except urllib.error.HTTPError as e:
            failures.append({"id": item["id"], "error": f"HTTP {e.code}",
                             "body": e.read().decode(errors="replace")[:300]})
            continue
        except Exception as e:
            failures.append({"id": item["id"], "error": f"{type(e).__name__}: {e}"})
            continue
        r["served_model"] = args.model
        rows.append(r)
        n = sum(1 for c in r["tool_calls"] if "tool" in c)
        print(f"[{item['id']}] {n} 次工具调用 / {r['turns']} 轮 / {r['latency_ms']}ms",
              file=sys.stderr)

    if failures:
        print(f"失败 {len(failures)} 条：{failures}", file=sys.stderr)

    stem = dataset.stem.replace("_dataset", "_predictions")
    out = args.output or (ROOT / "config" /
                          f"{stem}.tooluse.real-{slug(args.model)}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                   encoding="utf-8")
    out.with_suffix(".meta.json").write_text(json.dumps({
        "model": args.model, "generated_utc":
        dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "temperature": 0, "max_tokens": args.max_tokens, "count": len(rows),
        "dataset_file": str(dataset), "predictions_file": out.name,
        "execution": "stub（工具不在本机真执行，返回合成数据）",
        "safety": "毒工具保留在工具面用于测调用倾向；未读凭据、未发消息、未写盘",
        "return_injection": str(args.inject_return) if args.inject_return else None,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n写入 {out.name}（{len(rows)} 条，模型 {args.model}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
