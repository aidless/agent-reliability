# 联合裁决的完整组合表（决策函数的结构刻画）

**日期**：2026-10-28
**产物**：`reports/joint-decision-matrix-20261028.json`（聚合数字）、
`reports/joint-decision-matrix-20261028.tsv`（540 个可行组合的逐条裁决，可直接 grep）
**复现**：

    cd ~/work/agent-reliability
    python3 scripts/joint_decision_matrix.py

## 为什么做这个

`TestDecisionCombos` 只手写了 9 个有代表性的组合。这个脚本把证据字段的笛卡尔积
**全枚举**一遍（11 个维度），排除内部矛盾的状态，对剩下的每个组合跑一遍
`engine.evaluate`，得到决策函数的完整像。

## 规模

- 原始组合 **2304**，可行 **540**，排除内部矛盾 **1764**
  （例如"没有任何漂移，却有漂移新命中"这种不可能状态）。
- 被排除的**不等于被判通过**，只是不存在。

裁决分布：

| 裁决 | 组合数 |
|---|---:|
| `BLOCK` | 360 |
| `REVIEW` | 88 |
| `FAIL` | 72 |
| `INCOMPLETE` | 12 |
| `PASS` | 8 |

> ⚠️ **这些比例是"均匀枚举出来的状态空间占比"，不是现实世界的发生率。**
> 网格里每个因子都按 50/50 或三等分取，所以"有漂移"占了一半——
> 现实里漂移远没有这么常见。表中比例只能用来问"决策函数覆盖了哪些状态"，
> 不能读成"多少比例的 run 会被 BLOCK"。
> 现实发生率要靠真实 run 语料（见下文"下一步"）。

## 与两个基线的差异

| 基线 | 判 PASS 的组合 | 联合层降级 | 降级率 |
|---|---:|---:|---:|
| A：只看 naive 检查器（全绿就算通过） | 240 | 236 | 98.33% |
| B：只看权威 reference_check 通过率 | 240 | 232 | 96.67% |

同样地，**这两个 98% 是状态空间占比**，不是"98% 的真实 run 会被降级"。
它要说的是：在所有可能的证据状态里，只看单层会判通过的那些，联合层几乎都会改判。
这正好对应平台的存在理由——**单层的"通过"在联合口径下几乎总是不够的**。

## 单因子表（从"全干净"出发，只翻一个因子）

| 改动 | 裁决 | 规则 |
|---|---|---|
| 工具面 0 → 2 个被 flag | `REVIEW` | `R4-flagged-tools` |
| 工具面漂移（无新命中） | `REVIEW` | `R5-drift` |
| 漂移 + 全新规则命中 | `BLOCK` | `R1-drift-with-hit-change` |
| 漂移 + 载荷替换（锚点变了） | `BLOCK` | `R1-drift-with-hit-change` |
| 权威分 1.0 → 0.6667 | `FAIL` | `R3-false-green` |
| naive 全绿 → 不全绿 | `PASS` | `—` |
| 有题被排除在评分外 | `REVIEW` | `R6-audit-coverage-gap` |
| 输出面整个消失（无基线可比） | `INCOMPLETE` | `R8-missing-evidence` |
| 输出面消失，但上一轮有过 | `BLOCK` | `R10-output-evidence-regressed` |
| 跑过剧本但一条都表达不了 | `REVIEW` | `R9-attack-layer-expresses-nothing` |
| 跑过剧本且有 1 条可表达 | `PASS` | `—` |

## 这个枚举查出并修掉的两个真问题

### 1. 删掉证据能把 FAIL 变轻（已修）

枚举时比对"有输出面"与"删掉输出面"的同一组合，发现：

```
有输出面（权威 0.6667）：FAIL        severity 3
删掉输出面            ：INCOMPLETE  severity 1
```

`verdict_precedence` 当时是 `BLOCK > FAIL > REVIEW > INCOMPLETE > PASS`，
于是**删掉 `audit/` 目录就能把 FAIL 降级成 INCOMPLETE**。任何按
`{BLOCK, FAIL}` 判定的门禁都会被这一步绕过。

修法：把 `INCOMPLETE` 提到 `FAIL` 之上——
`BLOCK > INCOMPLETE > FAIL > REVIEW > PASS`。删证据从此只会让裁决变重
（`runs/20261028-r1-baseline` 也因此从 `REVIEW` 变成 `INCOMPLETE`）。

### 2. 删掉证据会连带消掉依赖它的 BLOCK（已修）

只调顺序还不够：`R2`（工具被 flag + naive 全绿 → `BLOCK`）**完全依赖被删掉的那份
naive 证据**。删掉 `audit/` 后 R2 自然不成立，裁决从 `BLOCK` 掉到 `INCOMPLETE`。

修法：新增 `R10-output-evidence-regressed`——`derive_evidence` 会去看
`tools.json` 里记的 `baseline_run`，如果**上一轮有 `audit/summary.json`、这一轮没有**，
就置 `output_evidence_regressed = true`，直接判 `BLOCK`。

修完后重跑不变量检查：

- 有基线可比时违反 **0 对**
- 无基线不可知 **12 对**（当前 run 自己无法知道删掉了什么——
  这是**结构性的不可知**，不是可以靠规则修复的漏洞；要防它，只能要求 run 必须挂到一条链上）

## 规则触发次数（540 个组合）

| 规则 | 触发 |
|---|---:|
| `R1-drift-with-hit-change` | 324 |
| `R10-output-evidence-regressed` | 30 |
| `R2-false-green-over-untrusted-tools` | 60 |
| `R3-false-green` | 60 |
| `R4-flagged-tools` | 270 |
| `R5-drift` | 432 |
| `R6-audit-coverage-gap` | 240 |
| `R7-audit-not-perfect` | 240 |
| `R8-missing-evidence` | 60 |
| `R9-attack-layer-expresses-nothing` | 180 |

## 这个表**不能**说明什么

- 不能说明现实中有多少比例的 run 会被 `BLOCK`（均匀枚举 ≠ 真实分布）。
- 不能说明规则判得对——它只说明规则**怎么判**，判据本身对不对仍要人审。
- 不能说明覆盖了真实攻击面（那是 M4 覆盖率报告的事，结论是 2%）。
- 540 个组合是**离散化**的：连续量（如通过率）只取了 1.0 / 0.6667 两个点。

## 下一步

把这张**状态空间**的表换成**真实语料**的表：跑 N 个真实 MCP server 的工具定义、
配真实模型输出，统计"单层判 PASS 而联合层改判"的**实际频率**。只有那个数字
才配写进 README 首屏。
