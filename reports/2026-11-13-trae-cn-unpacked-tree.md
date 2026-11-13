# TRAE CN 1.107.1 解包树：端点矩阵与能力面清单

**日期**：2026-11-13
**目标**：`/data4/rea-quarantine-20261109/work/trae/`（隔离区安装树）
**完整证据卡**：`~/rea-work-20261108/reports/2026-11-13-trae-unpacked-tree-analysis.md`（377 行 / 23,557 B）
**性质**：静态清单与配置面。**无运行时流量观测**，因此本卡不产出任何「外传了什么」的结论。

## 0. 身份

`Trae CN` `1.107.1`（`quality=stable`），commit `5d9926ed75dce7fa36dff87dbef5fb53e06b790a`，构建 `2026-11-02T15:37:51.333Z`，`enableTelemetry=true`。树 **9,013 文件 / 1,781 目录 / 1,823,575,811 B（1.70 GiB）**；主可执行 `usr/share/trae-cn/trae-cn` 202,947,800 B。

**先修一条旧判断**：上一轮记过「`resources/app/node_modules.asar` 值得拆」——该 asar **只有 28 B**，内容 `{"files":{}}`，是空壳。这一棵树的价值在 `resources/app/modules/` 的原生产物，不在 JS 层。

## 1. 端点矩阵（`product.json` 的 `bootConfig`，序列化 14,473 B）

| 用途 | 值 |
|---|---|
| 主 API（iCube / iCubeAgent / market / cue / ckg / hub） | `https://api.trae.com.cn` |
| 账号 / 增长 | `https://api.trae.cn` |
| agent / remote / ckg / cue / hub | `https://trae-api-cn.mchost.guru` |
| 自定义模型 WS | `wss://trae-ws-cn.mchost.guru/custom_model` |
| frontier | `wss://frontier.zijieapi.com/ws/v2`（boe 走 `frontier-boe.bytedance.net`） |
| 语音（火山） | `appId=4089030846`；`wss://openspeech.bytedance.com/api/v3/sauc/bigmodel`（大模型）、`/api/v2/asr`（小模型） |
| 遥测① tea | `appId={TRAE:711126, SOLO:932204}` → `https://mcs.zijieapi.com`，AB 走 `abtestvm.bytedance.com` |
| 遥测② slardar | `bid={TRAE:"trae_cn", SOLO:"solo_pc"}` → `https://mon.zijieapi.com` |
| 遥测③ slardarPC | `aid={TRAE:787976, SOLO:931506}` → `https://pc-mon.zijieapi.com` |
| CDN | CN `lf-cdn.trae.com.cn`；SG/US `lf-cdn.trae.ai`；USTTP `lf-static.traecdn.us`；私有 `cdn-tos.bytedance.net` |
| 连通性探测 | 内网 `icube-api.bytedance.net/trae/ping`、`icube-api-sg.tiktok-row.net/trae/ping`；CDN `grow-normal.trae.ai`、`api.trae.com.cn` |

**三套遥测是并列上报**（appId/aid 各不相同、落在不同统计口径），不是主备。
`mcpConfig` 为 **null** —— 没有静态 MCP 配置，实际 MCP 由云端按会话下发（见 §4）。

企业覆盖层 `__iCube_app_tenant_overrides.bytedance.hubConfig`：`appId={TRAE:1030603, SOLO:1017094}`、`serviceId=33555715`、明文 `appKey`（属客户端标识，不是用户凭据，别写成「泄露的密钥」）。

## 2. 原生产物：五个 `.so` + 两个可执行

| 文件（`modules/` 下） | 字节 |
|---|---|
| `ai-agent/libai_agent.so` | 262,358,696 |
| `ai-agent/libharness.so` | 236,737,856 |
| `ai-agent/bin/agent-tool-host` | 98,546,296 |
| `ai-agent/libtoolhost.so` | 96,054,848 |
| `ckg/binary/libckg.so` | 47,330,760 |
| `sandbox/trae-sandbox` | 24,463,640 |
| `ai-agent/libsscronet.so` | 10,468,520 |
| `sandbox/sbox_sdk.so` | 3,434,720 |
| `ai-agent/bin/ctx-cli` | 2,989,008 |
| `sandbox/crashpad_handler` | 2,944,040 |
| `sandbox/sbox.so` | 946,552 |
| `sandbox/bwrap` | 179,400（`bubblewrap 0.11.0`） |

### 2.1 `libharness.so` 是 LLM+MCP 协议层（字符串实测）

`tools/call` 1、`jsonrpc` 14、`mcp__` 2、`tool_use` 33、`function_call` 20、`anthropic` 3、`openai` 4、`tools/list` **0**、`streamable` **0**。
上下文片段给出：`mcp__is_locked force_locked`（MCP 锁定产品位）、`defaultresources/read tools/call … plugin_marketplace_name`（工具带插件市场来源）、`struct Notification with 4 elements`（serde 错误文案可反推结构规模）、`browser bridge response timed out`（存在浏览器桥通道）。

### 2.2 两个 `.so` 各链了同一张 endpoint 表

`libai_agent.so` 与 `libtoolhost.so` 按 byted/trae 过滤后**前 8 名计数逐项相同**：`api-bytedoc-bdsgdt.byted.org` 16/16、`api-bytedoc-sg.tiktok-row.net` 15/15、`bnpm.byted.org` 11/11、`docs.trae.cn` 9/9、`code.byted.org` 8/8、`bits.bytedance.net` 7/7、`api-bytedoc-ova-bdo.tiktok-us.org` 7/7、`api-bytedoc-useast2a.tiktok-eu.net` 6/6。
⇒ 不是「主进程 vs 工具宿主」的功能分层，而是**同一个基础 crate 被各自静态链接一份**（也是两者各近百 MB 的原因）。表的内容是**多区域内测端点矩阵**（cn-east / cn-north6 / sg / eu / de / ie / ie2 / id1a / id2a / my4a / no1a / useast2a / useast11a / useast14a / ova-bdo / ova2-bdo / maliva / pinnacle / bdsgdt + 各区域 `cloud.*`）。

### 2.3 沙箱是 bubblewrap，不是自研 syscall 过滤

`trae-sandbox` 里 `bwrap` 15 次、`unshare` 1 次；`seccomp` / `landlock` / `no-new-privs` / `ptrace` / `clone3` **均 0 次**；同目录直接带 `bwrap`（0.11.0）。
⇒ 任何「TRAE 沙箱能挡住 X」的表述，都得先回到这一条：bwrap 管的是**挂载/命名空间可见性**，不管系统调用白名单。

## 3. 108 个内嵌扩展里的能力面

publisher 分布：`vscode` 90、`byted-icube` 7、`cloudide` 4、`ms-vscode` 3、`trae`/`byted-solo`/`git-ai`/`icube` 各 1（109 目录，1 个无 manifest）。

### 3.1 `byted-icube.integrations-extended`（v0.0.4，`activationEvents=[]`，17 条命令）

- Supabase：`listProjects`、`getProject`、`pauseProject`、`restoreProject`、**`applyMigration`**、`listMigrations`、`listTables`
- LLM 配置：`getConfig`、`setConfig`、`checkConfig`、`deleteConfig`
- Stripe：`checkConfig`、`getAllPrices`
- 其它：`icube.figma.transform`、`larkCli.{install,checkUpdate,getCliStatus}`

⇒ agent 一旦被允许调这些命令，就能**对用户的 Supabase 项目执行迁移、读表结构**，并读 Stripe 价格表。是「能力面」不是「漏洞」，但威胁建模必须把它写进底物清单。

### 3.2 `cloudide.icube-im-bridge`（35 条命令）

飞书 14 + 微信 10（`login/stop/reply/push/unbind/streamStart/streamUpdate/streamEnd/uploadFile/checkBound/pause/resume/interaction/getEvents`）+ 会话绑定 6 + 开关 2。
⇒ 存在「IM 消息 ⇄ agent 会话」双向通道，含流式回写与文件上传。

### 3.3 `byted-solo.builtin-mcp`（依赖 `@byted-solo/computer-use-mcp` v0.81.3）

22 个 MCP 工具：`batch`、`check_permissions`、`click`、`clipboard`、`drag`、`get_app_state`、`get_value`、`grounding`、`launch_app`、`list_apps`、`menu`、`open_app`、`perform_action`、`press_key`、`request_permissions_gui`、`resolve_recorded_step`、`screenshot`、`scroll`、`select_text`、`set_value`、`type_text`、`verify_recorded_step`。

自带 4 条 deny 策略（`ComputerUseSafetyPolicy`）：`windows_untargeted_clipboard_paste`、`windows_terminal_identity`、`windows_system_key`、`macos_locked_use_protected_path`。终端 exe 名单含 `powershell`/`cmd.exe`/`wt.exe`/`WindowsTerminal`/`conhost`/`mintty`/`bash.exe`/`wsl.exe`。
**口径**：这四条是产品自带策略，**只约束 computer use 这一个工具**，不是安全边界。

Linux 后端（`linux-RQC5TI5Z.js`）是 **X11 命令拼装器**：`xdotool`、`xclip`、`scrot`、`wmctrl`、`import`、`xrandr`、`tesseract`；动作名含 `exec` 与 `kill`。

## 4. 本地落地 `~/.trae-cn`（1.6 GB）

| 项 | 实测 |
|---|---|
| `assistant` | 1.4 GB / 54,283 文件（会话与快照主体） |
| `skills` | 71 MB / 826 文件 / **77 个技能，全部 `marketplace` 来源** |
| `mcps` | 3.3 MB / 748 文件 / **按会话×场景下发**：`mcps/<session>/<profile>/mcp_plugin_<n>_<n>/`，profile 见过 `browser_use`/`solo_agent`/`solo_coder`/`search`，server 见过 `chrome-devtools`（9 会话）与 `github`（9 会话），每工具一个 json |
| `memory` | 2.3 MB / 267（192 `.jsonl` + 74 `.md`） |
| `builtin_skills` | 984 KB / 24：`TRAE-code-review`、`TRAE-debugger`、`TRAE-generate-mini-app`、`TRAE-security-review`、`_shared` |
| `trae-jwt-token` | **917 B 明文裸文件**（同机同用户进程均可读） |

77 个 marketplace 技能里有：`alipay-payment-integration`、`douyinpay-payment-integration`、`byted-bp-cdn-pagesdeploy`、`byted-mediakit-shared`、`local-computer-use`、`local-ocr-npu`、`local-vram`、`local-mineru`、`local-realtime-translator`、`free-compute-probe`、`hyperframes*`（10 个）、`tmlr-red-team-review`、`天眼一下`、`douyin-interact-creation`、`douyin-interactive-content-publish`。

## 5. `ckg` 与 `sandbox` 配置面

`ckg/meta.json`：`{"connections":[{"socket":{"port":50000}}],"env":{"LD_LIBRARY_PATH":"./binary"}}`；`binary/` 内 `libckg.so` + `libzmq.so.5` + `libsodium.so.18` + `libpgm-5.2.so.0`；`start.sh` 暴露 `ICUBE_MODULAR_DATA_DIR=$HOME/.icube`、`DB_PATH=$HOME/.icube/ai-chat/database.db`、`FILE_BASE_DIR=$HOME/.icube/ai-chat/snapshot`、`CKG_APP_ID=6eefa01c-1036-4c7e-9ca5-d891f63bfcd8`。
⇒ 代码索引走**本地 ZMQ(50000) + 本地 SQLite**。**实测本机 `~/.icube` 不存在**，索引从未构建或落在别处（未定位）。

`modules/ai-agent/checkpoint.sh`（302 B）是**给 agent 的自问自答提示词**：要求每次调工具前重读 RFC 全文、防止拿摘要冒充原文。配合 `trae-tob-git-ai-vscode` 的 `executeTraeCheckpoint` ⇒ checkpoint 在产品里是「上下文保真闸」，不是版本快照。

## 6. 结论与边界

**可用于能力审计的三条**：(a) 端点矩阵是「设计上的全集」，不等于运行时实际访问；(b) 「agent 能做什么」应以 §3 的命令清单为底物，不要以宣传页为底物；(c) 沙箱口径受限于 bwrap 的能力范围。

**本轮没做**：运行时流量（无观测）；`.so` 的符号级逆向（只有字符串与结构清单，无 `nm`/objdump/Ghidra）；`agent-tool-host` 与 `trae-sandbox` 的内部机制；108 个扩展的 `dist/` 实现（`builtin-mcp` 除外）；遥测事件名抽取（`out/main.js` 按 `(icube|trae|solo)[._]` grep 返回空，事件名应为运行时拼接）；`~/.icube` 定位；`trae-jwt-token` 的 scope 与有效期。

**复算入口**：见证据卡 §10 的只读命令清单。
