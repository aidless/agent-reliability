#!/usr/bin/env python3
"""从真实公开 MCP server 采集 `tools/list`，形成一个可扫描的语料。

**威胁模型（为什么这样做）**

1. 安装阶段需要网络：`npm install --ignore-scripts` —— 禁止执行任何 postinstall 脚本，
   把"装包"限制成"解压文件"。Python 侧用 `uv tool install`（同样不跑包内脚本）。
2. 运行阶段**完全无网络**：`unshare --user --map-root-user --net`，namespaces 里只有
   loopback。server 拿不到任何外部连接。
3. 只发两个 JSON-RPC 请求：`initialize` 与 `tools/list`。**从不调用 `tools/call`**，
   所以 server 的工具体不会被触发。
4. HOME 与 cwd 都指向临时目录，不挂载宿主机任何路径；带 `--args` 的 server
   （如 filesystem）只看到临时目录里的空文件夹。

这些措施降低但不是零风险：`tools/list` 本身仍会执行 server 的初始化代码。
只在明确授权后运行。

用法：
    python3 scripts/collect_mcp_tools.py --list
    python3 scripts/collect_mcp_tools.py            # 采集全部，写 corpus/
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent

PROTOCOL_VERSION = "2025-06-18"

# 只收"无需凭据即可 tools/list"的官方参考 server；github 之类要 token 的不收。
SERVERS = [
    {"id": "everything", "kind": "npm",
     "package": "@modelcontextprotocol/server-everything", "version": "2.1.0",
     "args": []},
    {"id": "filesystem", "kind": "npm",
     "package": "@modelcontextprotocol/server-filesystem", "version": "2.1.0",
     "args": ["{sandbox}"], "needs_sandbox": True},
    {"id": "memory", "kind": "npm",
     "package": "@modelcontextprotocol/server-memory", "version": "2.0.1",
     "args": []},
    {"id": "sequential-thinking", "kind": "npm",
     "package": "@modelcontextprotocol/server-sequential-thinking", "version": "2.0.0",
     "args": []},
    {"id": "fetch", "kind": "uvx",
     "package": "mcp-server-fetch", "version": "2026.10.28", "args": []},
    {"id": "git", "kind": "uvx",
     "package": "mcp-server-git", "version": "2026.10.28",
     "args": ["--repository", "{sandbox}"], "needs_sandbox": True,
     "sandbox_setup": "git_init"},
]


def npm_bin(prefix: pathlib.Path, package: str) -> pathlib.Path:
    """读 package.json 的 bin 字段，定位可执行文件，不靠猜名字。"""
    pkg_json = prefix / "npm" / "node_modules" / package / "package.json"
    meta = json.loads(pkg_json.read_text(encoding="utf-8"))
    bin_field = meta.get("bin")
    if isinstance(bin_field, str):
        rel = bin_field
    elif isinstance(bin_field, dict) and bin_field:
        rel = next(iter(bin_field.values()))
    else:
        raise RuntimeError(f"{package} 没有 bin 字段")
    return (pkg_json.parent / rel).resolve()


def install(spec: dict, prefix: pathlib.Path, log) -> None:
    if spec["kind"] == "npm":
        cmd = ["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund",
               "--prefix", str(prefix / "npm"),
               f"{spec['package']}@{spec['version']}"]
        env = None
    else:
        # 装到本 prefix 下，不污染用户的 ~/.local；--force 避免和已装的同名 shim 冲突
        cmd = ["uv", "tool", "install", "--force",
               f"{spec['package']}=={spec['version']}"]
        env = {**os.environ,
               "UV_TOOL_DIR": str(prefix / "uvtools"),
               "UV_CACHE_DIR": str(prefix / "uvcache")}
    log(f"install: {' '.join(cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"安装失败: {proc.stderr[-800:]}")


def server_command(spec: dict, prefix: pathlib.Path, sandbox: pathlib.Path) -> list[str]:
    args = [a.replace("{sandbox}", str(sandbox)) for a in spec.get("args", [])]
    if spec["kind"] == "npm":
        return ["node", str(npm_bin(prefix, spec["package"])), *args]
    # 直接调装好的二进制：运行阶段不需要 uv，也就不需要联网
    return [str(prefix / "uvtools" / spec["package"] / "bin" / spec["package"]), *args]


def isolate(cmd: list[str]) -> list[str]:
    if shutil.which("unshare"):
        return ["unshare", "--user", "--map-root-user", "--net", "--", *cmd]
    return cmd


def runtime_path() -> str:
    """给子进程一条最小 PATH，但必须包含 node / uv 这些运行时的真实位置。

    一开始只给了 `/usr/bin:/bin`，结果 node 装在 nvm 里找不到，
    initialize 直接超时——错误看起来像"server 不响应"，其实是 PATH 写错了。
    """
    dirs = []
    for exe in ("node", "uv", "uvx", "sh", "unshare"):
        found = shutil.which(exe)
        if found:
            d = str(pathlib.Path(found).parent)
            if d not in dirs:
                dirs.append(d)
    dirs += ["/usr/local/bin", "/usr/bin", "/bin"]
    return ":".join(dict.fromkeys(dirs))


def rpc_call(proc: subprocess.Popen, payload: dict, want_id: int,
             deadline: float) -> dict:
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == want_id:
            return msg
    raise TimeoutError(f"等 id={want_id} 的响应超时")


def collect_one(spec: dict, prefix: pathlib.Path, log) -> dict:
    sandbox = prefix / "sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)
    if spec.get("sandbox_setup") == "git_init":
        # git server 要求 --repository 指向一个真实仓库；沙箱里先 init 一个空的
        subprocess.run(["git", "init", "-q", str(sandbox)], check=False,
                       capture_output=True)
        (sandbox / "README.md").write_text("sandbox\n", encoding="utf-8")
    home = prefix / "home"
    home.mkdir(exist_ok=True)
    cmd = isolate(server_command(spec, prefix, sandbox))
    env = {
        "PATH": runtime_path(),
        "HOME": str(home),
        "PYTHONUNBUFFERED": "1",
    }
    log(f"run: {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=str(sandbox), env=env, bufsize=1,
    )
    try:
        deadline = time.time() + 60
        init = rpc_call(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                       "clientInfo": {"name": "agent-reliability-collector",
                                      "version": "0.1"}},
        }, 1, deadline)
        proc.stdin.write(json.dumps({"jsonrpc": "2.0",
                                     "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()
        listing = rpc_call(proc, {"jsonrpc": "2.0", "id": 2,
                                  "method": "tools/list", "params": {}}, 2, deadline)
    finally:
        proc.kill()
        try:
            err = proc.stderr.read()[-800:]
        except Exception:
            err = ""
        proc.wait(timeout=10)

    tools = (listing.get("result") or {}).get("tools") or []
    return {
        "server_id": spec["id"],
        "kind": spec["kind"],
        "package": spec["package"],
        "version": spec["version"],
        "protocol_version": (init.get("result") or {}).get("protocolVersion"),
        "tool_count": len(tools),
        "stderr_tail": err,
        "tools": [
            {"name": t.get("name"), "description": t.get("description", ""),
             "inputSchema": t.get("inputSchema") or {}}
            for t in tools
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", default=None, help="只采某个 server id")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.list:
        for s in SERVERS:
            print(f"{s['id']:<20} {s['kind']:<4} {s['package']}@{s['version']}")
        return 0

    targets = [s for s in SERVERS if not args.only or s["id"] == args.only]
    results, failures = [], []

    for spec in targets:
        def log(m):
            print(f"[{spec['id']}] {m}", file=sys.stderr)
        with tempfile.TemporaryDirectory(prefix=f"mcp-{spec['id']}-") as tmp:
            prefix = pathlib.Path(tmp)
            try:
                install(spec, prefix, log)
                row = collect_one(spec, prefix, log)
                results.append(row)
                print(f"[{spec['id']}] tools={row['tool_count']}", file=sys.stderr)
            except Exception as e:
                failures.append({"server_id": spec["id"], "error": str(e)[:800]})
                print(f"[{spec['id']}] FAILED {e}", file=sys.stderr)

    out = pathlib.Path(args.out) if args.out else (
        ROOT / "corpus" /
        f"mcp-tools-{dt.date.today().strftime('%Y%m%d')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "protocol_version": PROTOCOL_VERSION,
        "isolation": {
            "install": "npm install --ignore-scripts / uv tool install（不跑包内脚本）",
            "run": "unshare --user --map-root-user --net（namespaces 内只有 loopback）",
            "rpc": "只发 initialize + tools/list；从不调用 tools/call",
            "cwd_home": "临时目录，不挂载宿主机路径",
        },
        "servers": results,
        "failures": failures,
        "total_tools": sum(r["tool_count"] for r in results),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n采集 {len(results)}/{len(targets)} 个 server，"
          f"共 {sum(r['tool_count'] for r in results)} 个工具 → {out}")
    if failures:
        print("失败的：", [f["server_id"] for f in failures])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
