# 第一周最小开发任务（D1–D7）

> 原则：**全程本地、零 GPU、零 API key、零外部动作**。每天一个可验收交付物，
> 每个数字都能用一条命令复算。做不完就停在当日交付物，不跨天硬凑。

| 天 | 目标 | 交付物 | 验收标准 | 停止规则 |
|---|---|---|---|---|
| D1 | 两仓基线可复现 | `baseline.md` + `reports/baseline-20261028.txt` | 每个数字旁有一条能重跑的命令；两仓测试全绿 | 任一仓基线红 → 先修基线，不进入 D2 |
| D2 | 读懂规则包并扩边界 | `mcp-guard` 新规则 + 新用例 + 消融脚本 | 新用例在加规则前漏报、加规则后命中；良性用例误报仍为 0 | 误报上升 → 回退规则，改记为已知漏报 |
| D3 | 门禁自证 | `mcp-guard/scripts/mutation_control.py` + CI workflow | 故意改坏代码 → pytest **必须**变红；吞错误的门禁被判"没牙" | 门禁变绿 → 先修门禁，不谈别的 |
| D4 | 编排骨架 | `run.py` + `runs/<run_id>/{tools,meta,joint_verdict}.json` | 同输入两次跑，`tool_digests` 完全一致 | 产物不可复现 → 先修产物结构 |
| D5 | 接上输出面 | `run.py --dataset/--predictions` 分支 | 写出的权威分与 `summary.json` 一致（match=True） | 评分对不上 → 先对齐评分器，别改分数 |
| D6 | 联合实验 | `reports/2026-10-28-joint-experiment.md` | 一份能说明"为什么 naive 绿不可信"的证据 | 结论说不清 → 保留负面结果，不硬凑 |
| D7 | 收口 | `proposal.md` + 本 README | 契约 / 目录 / CI 三件事都能落到具体文件 | 任何一步需要外部动作 → 停在提案，不执行 |

## 执行状态（2026-10-28 收工时）

| 天 | 状态 | 证据 |
|---|---|---|
| D1 | 完成 | `baseline.md`、`reports/baseline-20261028.txt` |
| D2 | 完成 | `mcp-guard` 新增 `encoded-exfil` + `secret-read` 凭据路径扩展 + 2 条新用例；`scripts/measure_rule_ablation.py` |
| D3 | 完成 | `mcp-guard/scripts/mutation_control.py` + `.github/workflows/mutation-control.yml`，严格模式在干净副本里 PASS |
| D4 | 完成 | `run.py`；`runs/20261028-r1-baseline/`、`runs/20261028-r3-drift/` |
| D5 | 完成 | `runs/20261028-r2-joint/`（权威分 0.6667，与仓库口径一致） |
| D6 | 完成 | `reports/2026-10-28-joint-experiment.md`（含 2 个负面结果） |
| D7 | 完成 | `proposal.md`（**只写提案，不建 PR、不发布**） |

## 追加里程碑（M1 / M2，2026-10-28 续做）

> D1–D7 的记录保持原样不改写；这里是**之后**追加的一段。
> 起点是 `proposal.md` 第 6 节的里程碑表，本次只做 M1 与 M2，**M3 / M4 未做**。

| 里程碑 | 状态 | 交付物 | 验收（已实测） |
|---|---|---|---|
| M1 契约层 | 完成 | `contracts/{run,tool-evidence,joint-verdict}.schema.json`、`contracts/jsonschema_mini.py`、`contracts/validate.py` | 删必填字段 / 坏 digest / 未声明字段 / 坏 rules_version / 坏 commit 五种篡改全部被拦下（`TestSchemaRejectsTampering`）；手改 `decision.verdict` 被 `validate.py` 抓出（`TestRealRuns`） |
| M2 联合裁决层 | 完成 | `rules/joint_verdict.json`（R1–R10 + precedence）、`rules/engine.py` | 9 种证据组合各有判定（`TestDecisionCombos`）+ 540 个可行组合全枚举（`scripts/joint_decision_matrix.py`）；`contracts/validate.py --all` 对 3 个真实 run 全绿 |
| M3 编排层 CI | 完成（本地 + GitHub Actions） | `.github/workflows/ci.yml`（`gates` 双 Python 腿 + `e2e-smoke`）、`scripts/mutation_control.py` | `gates` 不依赖上游；`e2e-smoke` 真跑 `run.py` 并断言产物合契约。本地 10/10 变异被抓 |
| M4 接 agent-redteam | 完成 | `scripts/redteam_coverage.py`、`contracts/redteam.schema.json`、`reports/2026-10-28-redteam-coverage.md` | 12 向量 / 50 样本产出覆盖 + 不覆盖两张表；**覆盖率 1/50 = 2%**（负面结果，见报告） |

配套的门禁自证：`scripts/mutation_control.py`，14 个变异全部被测试抓到（0 逃逸）。

**本次修掉的三个真 bug**

1. `contracts/jsonschema_mini.py` 的 `$ref` 没把根文档传给子 schema，导致每份合法产物
   都被误判为"无法解析 $ref"（参照实现 `jsonschema` 判定 0 错）。
   现由 `TestSchemaCrossValidation` 逐条比对两个实现，防止再次漂移。
2. （D4 遗留）`run.py` 按**目录名排序**挑漂移基线，任何人在 `runs/` 下建一个 `tmp/` 目录
   都会让它悄悄变成下一次运行的基线。现改为按 `meta.json` 的 `created_utc` 取最新的一次，
   已用一个字典序最靠后的干扰目录实测通过。
3. （mcp-guard，D6 负面结果 2）`new_hits` 是**规则 id** 集合差集，载荷从 `~/.ssh`
   换成 `~/.aws` 时看不见。现改为 `(规则 id, 命中文本)` 级别，新增
   `changed_hits` / `hit_delta` / `alarm`；平台 R1 改为消费 `tool_drift_alarm`，
   r3 由 R1 直接判 `BLOCK`。

## 2026-10-28 晚：三项追加

| 项 | 做了什么 | 验收 |
|---|---|---|
| `new_hits` 内容级差集 | mcp-guard `guard/drift.py` 命中身份改为 `(规则 id, 命中文本)` | mcp-guard 测试 19 passed；退回规则 id 级别的变异被抓（2 failed） |
| 平台仓 + CI | 建 `aidless/agent-reliability`，`.github/workflows/ci.yml` 两个 job | main 上 [`run 40816361533`](https://github.com/aidless/agent-reliability/actions/runs/40816361533) 三个 job 全绿（gates 3.10 / gates 3.12 / e2e-smoke） |
| CI 门禁自证 | 推一个临时分支，把 R8 阈值 0 → 99，手动 `workflow_dispatch` | [`run 40816581949`](https://github.com/aidless/agent-reliability/actions/runs/40816581949) **按预期失败**，两条腿都报 `'PASS' != 'INCOMPLETE'`；分支已删除 |
| 三仓提交 | mcp-guard `13ae914`、auditable-llm-eval `f7e00d2`，**均已 push** | 两仓 CI 全绿（mcp-guard: ci + mutation-control；auditable: checks + release-validate + mutation-control） |
| 敏感锚点 | mcp-guard 命中身份改为 `(规则 id, anchor)`，修掉"纯措辞改动判 BLOCK" | mcp-guard 测试 19 → 23；6 个探针全符合预期 |
| M4 覆盖率 | `scripts/redteam_coverage.py` + `redteam.json` 契约 | 50 条样本 → 覆盖 1 / 不覆盖 49，**2%** |
| 决策全组合 | `scripts/joint_decision_matrix.py`：11 维笛卡尔积 → 540 个可行组合 | 查出并修掉两个门禁绕过：`INCOMPLETE` 排序、`R10` 证据回退；删证据不变量 0 违反 |
| 真实 MCP 语料 | `scripts/collect_mcp_tools.py`（npm --ignore-scripts + `unshare --net`，只发 initialize/tools/list）+ `scripts/scan_real_corpus.py` | 6 个官方 server / **53 个真实工具 → 0 误报**；CI 用 `--fail-if-flagged` 锁住这个不变量 |
| 契约补 `scorer_version` | `run.py` 对评分器文件取哈希，`run.schema.json` 要求该字段 | `runs/*/meta.json` 现记 `scorer_version=62b240b797547d69` |

## 明确不做（本周不做，也不建议下周偷做）

- 不装 GPU 依赖、不跑训练腿（`requirements_win3060.txt` 与本目录无关）
- 不调任何模型 API、不接真实 MCP server
- 不建 PR、不发布 release、不改账号设置
- 不把两个仓合并成一个包（它们职责不同，合并会毁掉各自的诚实性约束）
