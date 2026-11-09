# Related Work / 设计对照：Freebuff MCP 授权链（2026-11-09）

**性质**：引用卡 / related-work 登记。**不产生新实验、新 run、新统计结论**，只把已落盘的两份外部实证登记为设计对照材料。
**来源报告**：`reports/2026-11-09-freebuff-mcp-consent-source-audit.md`（源码级）、`reports/2026-11-09-freebuff-consent-runtime-probe.md`（模块级隔离探针）。
**主证据工作区**：`~/rea-work-20261108/`（证据卡 `reports/RESEARCH_EVIDENCE_CARD.md`、哈希清单 `reports/FILE_MANIFEST.tsv`、负责人基线 `reports/OWNER_STATUS.md`）。
**边界承诺**：不注入 `trace.json`、不改 `contracts/trace.schema.json`、不动任何既有 `runs/` 判决、不改 schema、不新增 gate 判据。

---

## 1. 可引用证据块（引用时整块带限定语，勿拆）

```
Freebuff MCP consent chain — shipped-artifact source audit + module-level runtime probe (2026-11-09)
ASAR SHA256      4a7b97630f13c33cb276749b1cdfa52cdaf70346773b1b4528816bb1fb779f46
REA parent       ev_d46fe4e72bd67240261c51b7ac75d102c4a2afb93521460ee3c01abb59c8faf8
mcp-consent-bridge.cjs  46efa1bd272cdc7f995b26104b89e5935d733a4a67509419d58e3df26d57c1d1 (592–593 lines* / 1847 AST)
consent-window.cjs      b9031aa4ec1ef3f97119309f517a53cacabab267336e7a914016f5b6a62762e6 (227–228 lines* / 709)
mcp-secret-store.cjs    03eb88b9e876e5fae01db61d637651e72380a4b395bdd779d2a81ef74b8e1181 (187–188 lines* / 556)
* wc -l 计行可能因末行无换行而少 1；以 ASAR 内字节与 SHA256 为准，范围值已实测复核。
probe            55/55, failed=[] (probe_bridge.json 29/29 + probe_store_window.json 26/26)
限定：源码级 + 隔离模块级运行时；非真实客户端端到端，非 source=external tool_calls，
      未注入 trace.json、未改 schema、未改既有 run 判决；静态图 coverage=partial，
      limitations 须随引用保留；未观测真实 keychain / 弹窗 / 登录态 / 网络请求。
```

**逐字可复算来源**：
- ASAR 哈希与三模块哈希：`~/rea-work-20261108/reports/FILE_MANIFEST.tsv` 中 `work/freebuff-src/*.cjs` 三行；ASAR 本体 `sha256sum /opt/Freebuff/resources/app.asar`。
- 行数 / AST 节点 / 视图证据 ID：`~/rea-work-20261108/reports/RESEARCH_EVIDENCE_CARD.md:7-11`。
- 父证据 ID 与 319 文件 / 157 IPC / 41 main handler：`~/rea-work-20261108/work/electron/Freebuff.evidence.json`、`~/rea-work-20261108/reports/FINAL_REPORT.md:27`。
- 55/55：`~/rea-work-20261108/work/runtime-probe/probe_bridge.json` 与 `probe_store_window.json` 的 `total` / `passed` / `failed` 字段。
- 行号锚点抽查：`mcp-consent-bridge.cjs:413` 的 bearer 等值比较、`mcp-secret-store.cjs:22/134` 的 `v10` 与 `0o600`、`consent-window.cjs:128/130/191` 的窗口隔离与本窗口 `webContents` 校验。

## 2. 与本平台的设计对照（只作对照，不作结论）

| 本平台关注点 | Freebuff shipped artifact 里的对应实现 | 可借鉴/需区分之处 |
|---|---|---|
| R11 / CAIT 轨迹层 | 授权决策由 main 进程持有（`/confirm` 的 `asking` 重入保护、409 busy、abort 即拒绝），审计与批准分离 | 轨迹层只记录过程，不替人类做授权；二者互补，不可互相替代 |
| 输出面防欺骗 | `escapeDisplay` 转义 C0/C1、bidi、零宽、行分隔符；`escapeLines` 限制续行；只显示 env 变量名 | 展示不可信 tool args 进审计视图前须做显示层转义，光有 schema 校验不够 |
| 凭据边界 | `safeStorage.encryptStringAsync`、Linux 拒 `v10` 硬编码 key、`refuseBackends` 拒 `basic_text`、`0o600` + 原子 rename、ticket 防并发写复活 | 注释明确「防偷盘/备份/其他账户，不防同用户进程」——threat model 的边界句应保留，别笼统写「安全存储」 |
| `source=external` 口径 | 本轮是 `shipped-artifact + source-level` 与 `module-runtime probe`，**不是**调用方给出真实 `tool_calls` 的运行时轨迹 | 与 `trace_integrity.py` 的 `external` 语义严格区分；报告里必须带限定行 |

## 3. 明确不写进本平台结论的内容

- 未运行 Freebuff 客户端：真实 `dialog.showMessageBox`、真实 OS keychain、真实 Electron `BrowserWindow`、真实登录态、真实 MCP connector 调用均未验证。
- 探针里的 token / 密文 / 凭据值全是 `dummy-*` 假数据；未读、未打印、未存储任何真实密钥。
- `Authorization` 是普通字符串等值比较，未做定时侧信道测量，未判为漏洞。
- 静态图全部 `coverage=partial`，`limitations` 数从 576 到 21519 不等；「未观测到」不等于「不存在」。WorkBuddy 证据另有 3 处 ASAR 完整性矛盾，须标 untrusted。
- 这是外部实现的对照材料，不是对本平台 R 系列 gate 的测试结果，不改变任何既有 run 判决。

## 4. 复算命令（只读；2026-11-09 实测输出）

```bash
cd ~/rea-work-20261108
sha256sum /opt/Freebuff/resources/app.asar
# 4a7b97630f13c33cb276749b1cdfa52cdaf70346773b1b4528816bb1fb779f46  /opt/Freebuff/resources/app.asar

grep -E "freebuff-src/.*\.cjs" reports/FILE_MANIFEST.tsv
# consent-window.cjs      b9031aa4…62e6 / mcp-consent-bridge.cjs  46efa1bd…d1d1 / mcp-secret-store.cjs    03eb88b9…1181

python3 -c "import json,glob;[print(p,json.load(open(p))['total'],json.load(open(p))['passed'],json.load(open(p))['failed']) for p in sorted(glob.glob('work/runtime-probe/probe_*.json'))]"
# work/runtime-probe/probe_bridge.json 29 29 []
# work/runtime-probe/probe_store_window.json 26 26 []

npx -y rea-agents@6.4.0 doctor --client codex --json | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['healthy'],[c['ok'] for c in d['scope_checks']])"
# True [True, True]
```

## 5. 登记状态

- 本文件与两份 `2026-11-09-freebuff-*.md` 均为未跟踪（untracked）状态，未 commit、未 push。
- 引用本卡时，正文里请同时给出 evidence_id、内容 SHA256 与「模块级、非端到端」限定。
- 若后续要做真实客户端端到端，需用户新一次明确同意并主动启动客户端、录 HAR / 进程轨迹；本卡不构成该授权。

## 6. 增量（2026-11-09 第二批）：WorkBuddy 隔离探针 + 五案例对照 + 工具链实战

**WorkBuddy（新增对照实现）**——源码抽取 + 语义复扫 + 隔离探针，方法学与 Freebuff 卡同构：

- ASAR SHA256 `5d32abcd796e887d8e79a5671d87d28ab5161690ab32855059f3219fdd669603`（`/opt/WorkBuddy/resources/app.asar`）。
- 抽取 14 文件（11 声明哈希 OK + 3 依赖基线，FAILED=0），清单 `~/rea-work-20261108/work/workbuddy-src/EXTRACT_MANIFEST.json`。
- 语义图流式复扫：23,171 节点全量、命中 5,608 行（`semantic_nodes.jsonl`）。
- 隔离探针 53/53 `failed=[]`（RED 演示在先）：`probe_wb_skills.js` 27（含 miniprogram-diagnostics 真实调用验证 401 时 query/body secret 不落日志）、`probe_wb_apps_host.js` 12、`probe_wb_compact.js` 14。
- 行为事实：日志脱敏、CLI 校验链、URL 钉定（https+域名钉定 static.d.gtimg.com+1MB）、`/responses/compact` 端点字面量——全部对真字节断言。

**五案例 trace 对照**（Qoder/Qoder-CN 全量种子本轮补跑完成）：

| 目标 | 图节点 | mcp | consent | load-skills | compact | approve |
|---|---|---|---|---|---|---|
| Freebuff | 1,388 | 32 | 27 | 10 | 14 | 0 |
| GrokBot | 3,341 | 14 | 0 | 0 | 6 | 0 |
| OpenCode | 24,439 | 41 | 1 | 0 | 未跑 | 未跑 |
| Qoder | 16,945 | 80 | 1 | 0 | 38 | 0 |
| Qoder-CN | 16,944 | 80 | 1 | 0 | 38 | 0 |

- `mcp` 五案例全命中；`consent` 命中 Freebuff 特异（27 vs 其它 0–1）；`approve` 五案例全 0（有效负结果）。
- Qoder 与 Qoder-CN 命中分布逐位相同 + 图规模差 1 节点 → 支持「CN 版同源重建」假设（未 diff 证实，不下"代码相同"结论）。
- BaiduNetdisk partial（682,470,796 B cancelled 包裹）流式还原中断边界：JS 解析完成（2,624 文件/0 失败/3,836 findings）、主图 86,122 节点/94,432 边部分建成、IPC 阶段全零行=未开始。

**工具链实战**：binwalk 3.1.0 对 Freebuff ASAR 签名扫描 11 hits（elf 2 → 内嵌 ripgrep 类二进制）；发现 binwalk 3.1.0 无 `--report`（REA FirmwareReports.js 期望），实际为 `-l/--log`——契约落差已记录。jadx-headless-mcp 0.7.1 对 rustdesk-1.5.0 APK 真实 MCP 会话 initialize→tools/list→load_apk→get_android_manifest 全通。

详细数字与复算命令：`~/rea-work-20261108/reports/2026-11-09-cross-case-comparison.md`、`reports/2026-11-09-workbuddy-evidence-card.md`、`reports/TRACE_INDEX.md`（已回填 Qoder 两行 ×5 种子）。
