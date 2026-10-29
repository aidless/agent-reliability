# agent-reliability — 把两个仓接成一条 Agent 可靠性链路

> 这是 2026-10-28 一次只读审计之后的落地目录。两个被审计的仓库在本目录下**没有被改动**；
> 后续改动都是经你授权后，在各自的 checkout 里单独做的。
>
> - `aidless/mcp-guard` → 输入面：工具定义是否被投毒、是否发生了 rug pull
> - `aidless/auditable-llm-eval` → 输出面：结论是否"假绿"、是否过度宣称

## 现在这个目录里有什么

    agent-reliability/
    ├── run.py                 # 编排骨架：一次跑完 L1 + L3，产物落在 runs/<run_id>/
    ├── config/
    │   ├── tools.example.json     # 4 个 MCP 工具（2 个有毒 + 2 个干净）
    │   ├── tools.drifted.json     # 同一份清单，但 send_message 的描述被改写过
    │   ├── joint_eval_dataset.jsonl     # 3 题评测集（符合 specs/test_50.schema.json）
    │   └── joint_eval_predictions.jsonl  # 3 条"模型输出"
    ├── contracts/              # M1 契约层：产物长什么样、坏了会被拦下
    │   ├── run.schema.json            # meta.json
    │   ├── tool-evidence.schema.json  # tools.json
    │   ├── joint-verdict.schema.json  # joint_verdict.json
    │   ├── jsonschema_mini.py         # 零依赖校验器（平台层不引第三方依赖）
    │   └── validate.py                # 校验三份产物 + 重算裁决并比对
    ├── rules/                  # M2 联合裁决层：规则是数据，引擎只求值
    │   ├── joint_verdict.json         # R1–R8 八条规则 + verdict_precedence
    │   └── engine.py                  # derive_evidence / evaluate / decide
    ├── tests/test_joint_verdict.py     # 36 个测试（契约 + 裁决 + 真实产物）
    ├── runs/                        # 每次运行的完整产物
    │   ├── 20261028-r1-baseline/    #   缺输出层 → REVIEW（缺证据 ≠ 通过）
    │   ├── 20261028-r2-joint/       #   假绿 → BLOCK（R2）
    │   ├── 20261028-r3-drift/       #   漂移 → BLOCK（R5 可见，R1 不触发）
    │   └── _archive/                #   历史产物（`_` 前缀，校验与测试都会跳过）
    ├── reports/                     # 基线快照、消融测量、联合实验报告
    ├── scripts/
    │   ├── measure_rule_ablation.py   # 规则消融：摘掉一条规则重算指标
    │   └── mutation_control.py        # 门禁自证：改坏实现，断言测试变红
    ├── baseline.md                  # D1 基线（每个数字对应一条可复算命令）
    ├── WEEK1_PLAN.md                # D1–D7 逐日清单：目标 / 交付物 / 验收 / 停止规则
    └── proposal.md                  # D7 提案 + M1/M2 落地状态

## 一条命令复现全部结论

    cd ~/work/agent-reliability

    # L1 + L3 联合跑一次（离线、零模型调用、零 API key）
    python3 run.py \
      --tools config/tools.example.json \
      --dataset config/joint_eval_dataset.jsonl \
      --predictions config/joint_eval_predictions.jsonl \
      --run-id my-run

    # 契约校验：校验三份产物 + 重算裁决并比对（手改过的裁决会被抓出来）
    python3 contracts/validate.py --all

    # 平台层测试（36 个）
    python3 -m unittest discover -s tests

    # 门禁自证：故意改坏实现，断言测试必须变红（8 个变异）
    python3 scripts/mutation_control.py

    # 规则消融：摘掉某条规则重算指标（不改文件）
    python3 scripts/measure_rule_ablation.py --rule encoded-exfil

输出（`runs/my-run/joint_verdict.json`）：

    {
      "input_guard":  { "scanned": 4, "flagged": 2, "verdict": "FLAG" },
      "output_audit": { "authoritative_rate": 0.6667, "naive_green": "3/3",
                        "deception_gap_points": 33.3 },
      "joint_verdict": { "headline": "naive 检查器 3/3 全绿，但工具面 FLAG、权威评分 0.6667" },
      "decision": { "verdict": "BLOCK", "rule_id": "R2-false-green-over-untrusted-tools",
                    "matched_rules": [ "R2-…", "R4-…", "R7-…" ] }
    }

## M1 / M2：契约层与联合裁决层

D7 提案里写的两条最小契约，现在已经落到可执行文件（**只在本目录内，未建仓、未建 PR**）。

**M1 契约层**（`contracts/`）

- 三份产物各有一份 JSON Schema：`run.schema.json` / `tool-evidence.schema.json` /
  `joint-verdict.schema.json`。
- 校验器是**零依赖**的 `jsonschema_mini.py`——平台层与两个被编排的仓保持同一条纪律
  （mcp-guard 的 `dependencies = []`，auditable-llm-eval 的评测管道只用标准库）。
  环境里若装了 `jsonschema`，它只作**参照实现**，由 `TestSchemaCrossValidation`
  逐条比对结论，不会进入运行时依赖。
- `contracts/validate.py` 做四件事：校验三份产物，**外加重算联合裁决并逐字段比对**——
  手改过的裁决、或产物与裁决不同步，都会被抓出来。

**M2 联合裁决层**（`rules/`）

- 判据是**数据**（`rules/joint_verdict.json` 的 R1–R8），引擎（`rules/engine.py`）
  只负责求值。改判据改 JSON，不改代码。
- 分级：`BLOCK > FAIL > REVIEW > INCOMPLETE > PASS`。**全部命中的规则都记进
  `matched_rules`**，最终结论取最严重的那一个——"为什么不是 PASS"始终可追溯。
- **缺证据 ≠ 通过**：缺必需证据层 → `INCOMPLETE`，与 `PASS` 严格分开。

| 证据组合 | 裁决 | 规则 |
|---|---|---|
| 工具干净 + 输出满分 | `PASS` | 无命中 |
| 工具有命中 + 输出满分 | `REVIEW` | R4 |
| 工具有命中 + 假绿 | `BLOCK` | R2 |
| 工具干净 + 假绿 | `FAIL` | R3 |
| 缺必需证据层 | `INCOMPLETE` | R8 |

**顺带修掉的运行期问题（D4 遗留）**：`run.py` 原来按**目录名排序**挑漂移基线，
于是任何人在 `runs/` 下建一个叫 `tmp/` 的目录，都会让它悄悄变成下一次运行的基线，
漂移结论会取决于目录名的字典序而不是实际跑过什么。现改为按 `meta.json` 的
`created_utc` 取**最新**的那次，已用一个字典序最靠后的干扰目录实测通过。

## CI（M3）

`.github/workflows/ci.yml` 有两个 job，分开是因为它们依赖的东西不同：

| job | 跑什么 | 为什么要分开 |
|---|---|---|
| `gates` | 36 个平台测试 + `contracts/validate.py --all` + `scripts/mutation_control.py`（Python 3.10 与 3.12 两条腿） | **不依赖上游**：只读已提交的 `runs/` 产物，上游不可达或改了都不影响这一层 |
| `e2e-smoke` | checkout `aidless/mcp-guard` 与 `aidless/auditable-llm-eval` 的 main，真跑一次 `run.py`；断言产物过契约、裁决是合法枚举 | 证明**接线**通。它**不断言具体裁决**——那取决于上游那一刻的代码 |

变异自证是这套 CI 的重点：`scripts/mutation_control.py` 逐个注入 10 个变异
（`$ref` 根文档、`additionalProperties`、digest pattern、precedence 顺序、R1/R2/R8
停用、引擎只取首命中、引擎丢弃 `missing_evidence`、alarm 忽略载荷替换），每个都
必须让测试变红。跑不过就说明那个"绿灯"是假的。

**门禁自证已实测**：另推一个临时分支，把 R8 阈值从 0 改成 99（缺证据不再判
`INCOMPLETE`），手动触发 CI —— 两条 Python 腿都按预期变红，报的正是
`'PASS' != 'INCOMPLETE'`。验证后分支已删除，main 保持全绿。

> **溯源说明**：`runs/*/meta.json` 里的 `repos.*.commit` 记录的是**本地提交**
> （mcp-guard `56aac4d`、auditable-llm-eval `f7e00d2`）。这两笔提交尚未 push 到
> GitHub，所以 `e2e-smoke` 用的是上游 main，产物裁决可能与 `runs/` 里的不同。
> push 之后按 `baseline.md` 的命令重跑一遍，两者即可对齐。

## 三条要记住的边界

1. **flagged ≠ 恶意。** mcp-guard 的规则是词法启发式，`FLAG` 只表示"值得人工看一眼"。
2. **naive 全绿 ≠ 通过。** 只查"有没有吐字、够不够长"的检查器，永远会全绿；这正是
   auditable-llm-eval 存在的理由。
3. **本目录的每个数字都可复算**，但样本量小（工具 4 个、题目 3 道、评测集 30 条），
   **不构成任何能力声明**。
4. **契约层只保证"产物没被手改 / 没不同步"**，它不保证判据本身是对的——判据由人审。

## 相关文档

- 逐日计划与验收：[`WEEK1_PLAN.md`](./WEEK1_PLAN.md)
- 基线快照：[`baseline.md`](./baseline.md) / [`reports/baseline-20261028.txt`](./reports/baseline-20261028.txt)
- 联合实验（含两个负面结果）：[`reports/2026-10-28-joint-experiment.md`](./reports/2026-10-28-joint-experiment.md)
- 提案（契约 / 目录 / CI）：[`proposal.md`](./proposal.md)
