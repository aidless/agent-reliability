# 真实 MCP 工具定义扫描：0/53 误报（第一次真实语料）

**日期**：2026-10-28
**产物**：`corpus/mcp-tools-20261028.json`（语料）、`reports/real-mcp-scan-20261028.json`（扫描结果）
**复现**：

    cd ~/work/agent-reliability
    python3 scripts/collect_mcp_tools.py      # 采集（需网络，见下方隔离措施）
    python3 scripts/scan_real_corpus.py       # 扫描

## 一句话结论

**6 个官方参考 MCP server、53 个真实工具、`tools/list` 原样采集 → 规则包命中 0 个。**
在真实良性工具上，这批规则**没有误报**。

这是本仓第一次用**真实**输入（而不是自造样例）测误报。

## 怎么采的（以及为什么这样做）

| 阶段 | 做法 | 为什么 |
|---|---|---|
| 安装 | `npm install --ignore-scripts` / `uv tool install` | 禁止执行包内 postinstall 脚本，把"装包"限制成"解压文件" |
| 运行 | `unshare --user --map-root-user --net` | namespaces 内只有 loopback，server 拿不到任何外部连接 |
| 通信 | 只发 `initialize` + `tools/list` | **从不调用 `tools/call`**，工具体不会被触发 |
| 文件系统 | HOME 与 cwd 都是临时目录 | 不挂载宿主机任何路径；`filesystem` server 只看到空沙箱 |

版本全部钉死，记录在语料里；协议版本 `2025-06-18`。

## 版权与归属

语料里的工具描述版权归各 server 作者，按其包的许可证使用；本仓只保存
`tools/list` 的原样输出用于误报测量，并在语料里记录 `package` + `version` 作为归属。
本仓不再分发这些包本身，只分发它们的公开接口描述。

## 结果

| server | 包 | 版本 | 工具数 | 被 flag |
|---|---|---|---:|---:|
| `everything` | `@modelcontextprotocol/server-everything` | 2.1.0 | 16 | 0 |
| `filesystem` | `@modelcontextprotocol/server-filesystem` | 2.1.0 | 14 | 0 |
| `memory` | `@modelcontextprotocol/server-memory` | 2.0.1 | 9 | 0 |
| `sequential-thinking` | `@modelcontextprotocol/server-sequential-thinking` | 2.0.0 | 1 | 0 |
| `fetch` | `mcp-server-fetch` | 2026.10.28 | 1 | 0 |
| `git` | `mcp-server-git` | 2026.10.28 | 12 | 0 |
| **合计** | 6 个 | — | **53** | **0** |

`flag_rate = 0.0000`。

## 近失分析：真正值得看的那部分

有 **21** 个工具的描述里出现了 "key / token / secret / credential /
password / env / file / path / url / shell" 这类词，但**一个都没被 flag**。最尖锐的一例：

> `everything/get-env`：*"Returns all environment variables, helpful for debugging MCP
> server configuration. Values of credential-like names (a KEY, TOKEN, SECRET, PASSWORD,
> PASSWD, CREDENTIAL, AUTH or COOKIE name segment) are masked as `<redacted>` unless
> GET_ENV_INCLUDE_SECRETS is set..."*

这个工具字面上就在列环境变量、字面上提到了 KEY/TOKEN/SECRET——规则包**没有**命中它，
因为它没有"把凭据读出来塞进参数/发出去"的指令。这正是规则有意的收窄：
**命中要求的是外带动作，不是敏感词**。

另 10 个近失（全部未命中）：

| server | 工具 | 出现的敏感词 |
|---|---|---|
| `everything` | `get-env` | key, token, secret, credential, password, env |
| `everything` | `get-header-params` | http |
| `everything` | `gzip-file-as-resource` | file |
| `filesystem` | `read_file` | file |
| `filesystem` | `read_text_file` | file |
| `filesystem` | `read_media_file` | file |
| `filesystem` | `read_multiple_files` | file, path |
| `filesystem` | `write_file` | file |
| `filesystem` | `edit_file` | file |
| `filesystem` | `create_directory` | path |

## 这条结果能说明什么

- ✅ 在 **53 个真实良性工具**上，当前规则包**零误报**。
- ✅ 语料是 `tools/list` 原样输出，不是手抄的；采集过程可复核（版本 + 隔离方式都记了）。
- ✅ 结合自造良性集的 0/11，现在有两组独立的良性样本都是 0 误报。

## 这条结果**不能**说明什么

- ❌ **不是召回率**。这 53 个工具全是良性，语料里没有一条毒工具。
  "0 误报" 与 "能抓到多少攻击" 是两件事，后者仍然是未知数。
- ❌ 不是整个 MCP 生态的随机样本：只有 6 个**官方参考** server，
  真实第三方 server 的写法（尤其是中文/长描述/嵌套 schema）没有覆盖。
- ❌ 不能说明规则对"模仿良性措辞的攻击"有效——`get-env` 这种写法可以被攻击者抄走。
- ❌ 53 个样本的 95% 置信上界仍然不低（约 5.5%），所以"0 误报"不等于"误报率低于 1%"。

## 下一步

- 扩大语料：接入更多第三方 server（含中文），把 53 抬到几百，误报率的置信区间才有意义。
- 补召回：往语料里**受控注入**已知投毒工具（用 mcp-guard 自己的 19 条毒用例做变异），
  在同一批真实工具上同时测误报与召回。
