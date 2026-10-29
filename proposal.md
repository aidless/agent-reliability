# 提案：Agent Reliability Platform 的最小契约（D7）

**日期**：2026-10-28（2026-10-28 续做后更新）
**状态**：**提案 + M1/M2 落地记录**。M1/M2 已在 `~/work/agent-reliability/` 本地目录
实现并自测，**仍未建仓、未建 PR、未发布、未接真实 MCP server**——这些需要你另行授权。
**依据**：`reports/2026-10-28-joint-experiment.md`、`baseline.md`、两仓 README。

## 1. 要解决什么

现在两个仓各自成立，但**互相看不见对方**：

- `mcp-guard` 知道工具被 flag 了，但不知道这轮 agent 的结论是什么；
- `auditable-llm-eval` 知道结论"假绿"，但不知道这轮 agent 用过什么工具。

平台要做的第一件事不是加功能，而是**把一条 run 的三段证据绑在同一个 id 下**，
让"工具面 FLAG + 输出面 naive 全绿"这种组合**能被自动看见**。

## 2. 最小契约（3 个字段起步）

| 字段 | 含义 | 谁产生 | 落在哪 |
|---|---|---|---|
| `run_id` | 一次运行的唯一 id | 编排层 | `runs/<run_id>/meta.json` |
| `tool_digest` | 每个工具定义的 sha256 | mcp-guard（`digest_tool`） | `runs/<run_id>/tools.json` |
| `rules_version` | 规则包内容的 sha256 前 16 位 | 编排层（对 `guard/rules.py` 取哈希） | `meta.json` + `tools.json` |

扩展建议（第 4 个字段，强烈建议一起加）：

| `scorer_version` | 评分器内容的 sha256 前 16 位 | 否则规则改了、评分器也改了，
历史 run 无法区分是"模型变了"还是"判分标准变了" |

> 契约从"3 个字段"起步，是因为 auditable-llm-eval 已经证明了它的价值：
> 它的 `config.yaml` 钉住 model tag / temperature / seed，
> 让 `verify_copilot_run.py` 能重算任何一次 committed run。
> 平台要的是同一件事的通用版。

## 3. 目录结构（M1/M2 落地后的实际形态）

    agent-reliability/                 # 编排层（本目录）
    ├── run.py                         # 一次跑完 L1 + L3 + 联合裁决
    │                                  #   （原提案里的 runners/ 两个薄封装没有单独建，
    │                                  #    直接在 run.py 里 import 两仓的公共 API——
    │                                  #    少一层间接，少一处会漂移的复制）
    ├── contracts/
    │   ├── run.schema.json            # meta.json 的 JSON Schema
    │   ├── tool-evidence.schema.json  # tools.json 的 JSON Schema
    │   ├── joint-verdict.schema.json  # joint_verdict.json 的 JSON Schema
    │   ├── jsonschema_mini.py          # 零依赖校验器
    │   └── validate.py                 # 校验 + 重算裁决并比对
    ├── rules/                        # 平台自己的决策规则（可审、可测）
    │   ├── joint_verdict.json         # R1–R8：什么样的组合算"不可信"
    │   └── engine.py                  # 只求值，不改判据
    ├── tests/test_joint_verdict.py   # 35 个测试
    ├── scripts/mutation_control.py   # 门禁自证
    └── runs/<run_id>/
        ├── meta.json                 # 契约字段 + 两个仓的 commit
        ├── tools.json                # 逐工具：digest / hits / drift
        ├── audit/                    # report.jsonl / summary.json / naive_verdicts.jsonl
        └── joint_verdict.json        # 三层证据 + decision（联合裁决）

对应到两个仓的**边界**：

- 编排层**只做搬运与并排**，不改两仓的任何判分逻辑；
- mcp-guard 继续只管"工具面"，auditable-llm-eval 继续只管"结论面"；
- 跨仓的东西（联合裁决规则）**只放在编排层**，不塞回任一仓。

## 4. CI 计划（每条都有"怎么证明它有牙"）

| 层 | 门禁 | 自证方式 | 现状 |
|---|---|---|---|
| mcp-guard | `pytest tests/ -q` | `scripts/mutation_control.py`：故意注入失败测试，断言 pytest 必须变红；并验证"吞错误"的门禁会被判"没牙" | 已实现（本地严格模式 PASS） |
| auditable-llm-eval | `python3 scripts/validate_release.py` | 已有 `mutation-control.yml`：注入 spec 漂移，断言门禁必须变红并点名 | 已有（上游 CI 全绿） |
| 编排层 | `python3 contracts/validate.py --all` + `python3 -m unittest discover -s tests` | `scripts/mutation_control.py`：8 个变异（`$ref` 根文档、schema 约束、precedence 顺序、R2/R8 停用、引擎只取首命中、丢弃 missing_evidence），断言测试必须变红 | 已实现（8/8 变异被抓到，0 逃逸） |

## 5. 与第三块（agent-redteam）的接口

`aidless/agent-redteam` 已经是公开仓（`attacks/v01…v12` + `defenses` + `aggregators`），
`mcp-guard` 的待办里也写着"与 agent-redteam 剧本联动（93 测试复用）"。
接口建议只有一条：**剧本产出的每条攻击，都要能被工具面规则表达或被明确标为"规则不覆盖"**——
这正是本目录 `measure_rule_ablation.py` 已经在做的事（逐条看哪些用例还在漏）。

## 6. 里程碑

| 里程碑 | 内容 | 验收 | 状态（2026-10-28） |
|---|---|---|---|
| M1 | `contracts/*.schema.json` + `meta.json` 按 schema 校验 | 改动一个字段能被 schema 拦下 | **完成**：`contracts/` 3 份 schema + 零依赖 `jsonschema_mini.py` + `validate.py`（校验 + 重算裁决比对）；5 种篡改全部被拦下 |
| M2 | `rules/joint_verdict.json`（联合裁决规则）+ 它的测试 | 三种组合（工具干净+输出干净 / 工具脏+输出绿 / 工具脏+输出红）各有判定与测试 | **完成**：R1–R8 八条规则 + `verdict_precedence`，`rules/engine.py` 只求值；9 种组合各有判定，35 个测试全绿 |
| M3 | 编排层 CI（端到端 + 变异自证） | 故意改坏 → 门禁必须变红 | **完成**：`.github/workflows/ci.yml`（`gates` 双 Python 腿 + `e2e-smoke`）；`scripts/mutation_control.py` 10/10 变异被抓 |
| M4 | 接 `agent-redteam` 剧本 | 一次剧本回放产出"规则覆盖 / 不覆盖"两张表 | **完成**：`scripts/redteam_coverage.py` 对 12 向量 / 50 样本产出两张表；**覆盖率 1/50 = 2%**，49 条明确标为"规则不覆盖"（见 `reports/2026-10-28-redteam-coverage.md`） |

## 7. 明确未做 / 未验证

- **未建任何仓库、PR、release、issue**，未 push 任何东西。
- **未接真实 MCP server**，全部工具样例是自造的 4 个。
- **未接真实模型**，输出面用的是手工构造的 3 条输出。
- **未跑 GPU 训练腿**（与本提案无关，也未验证）。
- **联合裁决规则已写但只覆盖 10 条规则**：R1–R10 是为这批 4 工具 / 3 题的样例写的，
  尚未在真实语料上验证过召回率。`attack_sim_present` 现在会随 `redteam.json`
  变成 true，但它的语义是**可表达性覆盖**（2%），不是运行时拦截率。
- **契约层只管"没被手改、没不同步"**，不管判据本身对不对——判据仍需人审。
- 两仓的改动**已本地 commit**（mcp-guard `56aac4d`、auditable-llm-eval `f7e00d2`），
  **尚未 push**；`runs/*/meta.json` 记录的正是这两个 commit。
