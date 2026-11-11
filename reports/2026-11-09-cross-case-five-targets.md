# 跨案例对照报告 — REA shipped-artifact 分析五案例（2026-11-09）

> 所有数字来自落盘 trace JSON / probe JSON / evidence JSON，逐条可复算；复算命令在各节末尾。

## 1. 案例清单与证据等级

| 案例 | 证据父图 | 完整性 | 本次新增证据 |
|---|---|---|---|
| Freebuff | `work/electron/Freebuff.evidence.json`（ev_d46fe4e72bd6…） | 干净 | binwalk 签名扫描、jadx 真机冒烟（工具链实战） |
| WorkBuddy | `work/electron/WorkBuddy.evidence.json`（484,359,447 B） | 3 条 integrity contradictions（node-pty/better-sqlite3，untrusted） | 源码抽取 14 文件 + 语义复扫 + 隔离探针 53/53 |
| Qoder | `work/electron/Qoder.evidence.json`（ev_5d88d290c744…） | 干净 | 全量 trace 补跑 5 种子 |
| Qoder-CN | `work/electron/QoderCN.evidence.json` | 干净 | 全量 trace 补跑 5 种子 |
| BaiduNetdisk | **`work/electron/BaiduNetdisk.evidence.json`（ev_4b2124d5681b…，1,115,993,105 B，rc=0 全量）**；旧 `BaiduNetdisk.partial.evidence.json`（ev_7a5ff1dbb78b…，682,470,796 B cancelled）保留作对照 | **干净（全量完成，2026-11-10）** | 全量 JS 分析 + 17 个原生 ELF 反编译（`reports/2026-11-11-baidunetdisk-native-modules.md`） |

## 2. 五案例种子命中对照（trace-application-feature，direction=both）

种子命中数（matched_seeds）与覆盖状态：

| 目标 | 图节点 | mcp | consent | load-skills | compact | approve | coverage |
|---|---|---|---|---|---|---|---|
| Freebuff | 1,388 | 32 | 27 | 10 | 14 | 0 | partial ×4 / no-match |
| GrokBot | 3,341 | 14 | 0 | 0 | 6 | 0 | partial ×2 / no-match ×3 |
| OpenCode | 24,439 | 41 | 1 | 0 | 2 | 0 | partial ×3 / no-match ×2 |
| Qoder | 16,945 | 80 | 1 | 0 | 38 | 0 | partial ×3 / no-match ×2 |
| Qoder-CN | 16,944 | 80 | 1 | 0 | 38 | 0 | partial ×3 / no-match ×2 |

（GrokBot 数字为 TRACE_INDEX.md 原有行；Qoder 系与 OpenCode compact/approve 为本研究线新跑，`work/electron/{qoder,opencode}_trace_runlog.json` 汇总。）

### 横向读数（全部可从上表复算）

1. **`mcp` 是五案例共同词汇**：所有已跑案例均命中（14–80），无一处 0。
2. **`consent` 命中高度 Freebuff 特异**：Freebuff 27 vs 其它案例 0–1。Qoder/OpenCode 各仅 1 次
   （字符串级 contains 命中，非语义链）——"consent chain"作为代码词汇是 Freebuff 代码库特征。
3. **`approve` 五案例全 0**：包括 Freebuff 自身。作为种子词在 shipped artifact 认证图中无对应——
   追踪层的有效负结果，与 Freebuff 探针层"审批按钮存在但词形不同"互补。
4. **Qoder 与 Qoder-CN 是近似孪生分布**：图规模差 1 个节点（16,945/16,944）、观测差 2（31,124/31,122）、
   推断差 1（922/923），而五个种子命中分布**逐位相同**（80/1/0/38/0）。
   一致支持「CN 版为同源重建/换皮」的判断；两份 trace 均为 partial coverage。
5. **图密度与命中数无正相关**：OpenCode 图最大（24,439）命中 41；Qoder 图居中（16,945）命中最多（80）。
   命中数由词汇在代码中的真实出现密度决定，不是图规模。
6. **终端路径与 native_handoffs（Qoder 系）**：partial 轨迹全部 ~8,451–8,474 条终路径、13 条 native_handoffs，
   与节点数（16,945）同数量级稳定性——同一底图重跑差异仅 ±23 条终路径。

## 3. WorkBuddy 对照位（源码/探针层，非 trace 层）

WorkBuddy 本轮未跑 trace（其 evidence 的 semantic 图为 23,171 节点，命中行 5,608 —— 见
`work/workbuddy-src/semantic_nodes.jsonl`），对照位用源码+探针证据：

- 探针 53/53（skills 27 + apps-host 12 + compact 14），全部 RED 演示在先。
- 与 Freebuff 的主题对位：Freebuff=consent chain 三模块；WorkBuddy=日志脱敏/CLI 校验链/URL 钉定
  /`/responses/compact` 端点字面量（`reports/2026-11-09-workbuddy-evidence-card.md` §探针实测）。
- 两个案例都验证了「源码级结论可被隔离运行时探针复验」这一方法学闭环（55/55 + 53/53，failed=[]）。

## 4. BaiduNetdisk partial：中断边界还原（流式，682,470,796 B）

> **2026-11-10 状态更新**：本节记录的是**旧 partial 包裹**的中断边界，作为「进程级失败边界」的历史证据保留。同一 artifact（app.asar SHA256 `87a6e39f…`）已于 2026-11-10 全量重跑成功——`work/electron/batch_baidu.sh 7200 1800000 4096` → **rc=0，48 分 12 秒，`work/electron/BaiduNetdisk.evidence.json` 1,115,993,105 B，evidence_id `ev_4b2124d5681bc5ddc457b42987c046fad805395a11b7f39c1a9e63a6414f0008`**。逐项对照：JS 文件 2,624→**29,886**、AST 节点 389,723→**23,623,733**、findings 3,836→**111,895**、modules 0→**265**、`ipc.operations` 0→**66**、`sender_validation_observations` 0→**352**；但 `graph.coverage=partial` 且 `semantic_graph.coverage.truncated=true`——**全量 ≠ 完整**。原生面见 `reports/2026-11-11-baidunetdisk-native-modules.md`。

父证据：`ev_7a5ff1dbb78b97e3d59fd8b9ea95daf17f0d97c3cd9e8f0ad11ea5e6f0e02e79`，
subject `app.asar` SHA256 `87a6e39fb1082e458cd183cbee7ed9527bfc4a13edee2f51b7bded54df91330e`
（`/opt/baidunetdisk/resources/app.asar`），integrity_policy=fail，authority=shipped-artifact，
confidence=derived。

已跑到的阶段（`normalized_result.statistics`，ijson 流式读取）：

| 阶段指标 | 值 | 读数 |
|---|---|---|
| relevant_files | 30,592 | 文件枚举完成 |
| text_bytes_read | 191,572,290 | 文本层读取完成 |
| parsed_javascript_files | 2,624 | JS 解析完成 |
| parse_failures | 0 | 解析零失败 |
| visited_ast_nodes | 389,723 | AST 遍历完成 |
| findings | 3,836 | 规则发现完成 |
| modules | 0 | 模块归组阶段**未达/中断** |
| graph.nodes / graph.edges | 86,122 / 94,432 | 主图部分建成 |
| semantic_graph.nodes / relations | 41,624 / 11,948 | 语义图层部分建成 |
| summary.ipc.* 全部 | 0 | IPC 分析阶段**完全未开始** |
| summary.sender_validation_observations | 0 | 同上 |

**中断边界判定**：JS 解析与 AST 遍历完成（2,624 文件 / 0 失败），主图/语义图部分建成，
IPC 与模块归组阶段未开始（全 0 行）。与 trace 层五案例互补——这是**进程级失败边界**的
直接证据（cancelled 包裹保留了已产出部分，未写入部分全零）。

## 5. 工具链实战（Step② 产物， Freebuff 载体）

- **binwalk 3.1.0**（`work/engines/binwalk/binwalk`）：对 21,374,479 B ASAR 签名扫描 11 hits
  （copyright 8 / elf 2 / svg 1）→ `work/firmware/freebuff_asar_binwalk_report.json`（4,299 B，
  list[{"Analysis":{file_path,file_map}}] 格式）。ELF 命中提示 ASAR 内嵌 ripgrep 类二进制。
  **2026-11-10 更正**：原写「REA 期望 `--report`，binwalk 只有 `-l/--log`，契约落差需 shim」——**该说法有误**。
  实读 REA 6.4.0 `dist/firmware/FirmwareProvider.js`：`--report` 只属 **unblob** 路径（:233）；
  **binwalk 路径（:193-201）实参 `--quiet --search-all --threads 1 --log <reportPath>`**，与 binwalk 3.1.0 完全对齐，
  **无契约落差、不需 shim**。错误根因：混用两引擎实参列表（STEP4_TOOLCHAIN.md 同源错误，已更正）。
- **jadx-headless-mcp 0.7.1**（`dist/android/jadx-headless-mcp-0.7.1-all.jar`，SHA256
  `6e5eacf500b64292bfb73c49797c1958f6ee44646e43e868039ae7feb573ff75`）：对
  `/home/liuzewen/Downloads/rustdesk-1.5.0/rustdesk-1.5.0-universal-signed.apk` 走真实 MCP stdio
  会话 initialize → tools/list → load_apk → get_android_manifest **全通**
  （`work/firmware/jadx_mcp_rustdesk_smoke.json`，`ok:true`，零 error）。
  REA 内部钉定值与 Release 资产逐字一致（`STEP4_TOOLCHAIN.md`）。

## 6. 复算命令

```bash
cd ~/rea-work-20261108
python3 -c "import json; d=json.load(open('work/electron/qoder_trace_stats.json')); print(json.dumps(d,indent=1))"
# 五案例命中表 ← work/electron/qoder_trace_stats.json + reports/TRACE_INDEX.md
# BaiduNetdisk 中断边界 ← 下面的 ijson 流式读（682MB，勿 json.load）
python3 - <<'EOF'
import ijson
p='work/electron/BaiduNetdisk.partial.evidence.json'
want=('statistics.','summary.ipc')
with open(p,'rb') as f:
    for pre,ev,val in ijson.parse(f,buf_size=262144):
        if pre.startswith('normalized_result.') and ev in ('string','number') \
           and any(pre.startswith('normalized_result.'+w) for w in want):
            print(pre.split('.',2)[2],'=',val)
EOF
node work/runtime-probe/probe_wb_skills.js          # 27/27
node work/runtime-probe/probe_wb_apps_host.js       # 12/12
node work/runtime-probe/probe_wb_compact.js         # 14/14
cat work/firmware/jadx_mcp_rustdesk_smoke.json      # ok:true, 4 steps
python3 -c "import json;d=json.load(open('work/firmware/freebuff_asar_binwalk_report.json'));print(len(d[0]['Analysis']['file_map']),'hits')"
```

## 7. 边界与不做的事

- 不把 `matched_seeds=0` 写成"功能不存在"——那是字符串级追踪的有效负结果，语义存在性归探针层。
- 不把 Qoder/Qoder-CN 命中分布逐位相同写成"代码相同"——支持的是同源假设，需 diff 证实（未做）。
- BaiduNetdisk **partial** 的全零行是"阶段未达"，写成"无 IPC"就是编造；**全量**的 `ipc.paired_renderer_transmissions=0` 也不是"无 IPC"，而是 66 条里 62 条用动态通道表达式、静态不可配对（`limitations` 原话）。
- WorkBuddy 3 条 integrity contradictions 文件（node-pty/better-sqlite3）引用必须带 untrusted 标记。
- OpenCode compact/approve **已补跑**（compact 命中 2 / 109,851,405 B / partial；approve 命中 0 / 2,124 B / no-match）。旧 684 B 是 ENOENT 错误 stub，不是有效负结果。
