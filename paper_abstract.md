# 论文摘要 — agent-reliability

> 一份**真实论文摘要文档**，对应本仓的实际研究贡献。所有数字均来自仓库内
> 可复算的实现（`scripts/`、`reports/`、`runs/`），不虚构。

## 标题（草稿）

**Reliable-by-construction agent tooling: a joint verdict chain over
tool-injection and output-overclaim layers**

## 摘要（Abstract，草稿）

Agent 工具与评测的可靠性常被拆成两个互不相干的层：工具定义会不会被投毒
（tool-injection / rug pull），以及评测结论是不是"假绿"（over-claiming）。两者
各自"看起来正常"的组合问题——一个 naive 检查器在输出上永远全绿、而工具面已被
flag——只有在**联合**看时才暴露。

我们提出一条**可复算的联合裁决链路**：零第三方依赖、零模型调用、零 API key，
把工具面（mcp-guard，检查工具定义投毒）与输出面（auditable-llm-eval，检查结论
可信度）的产物按一套数据驱动的规则（R1–R10）联合裁决。关键设计是**判据是数据、
引擎只求值**，以及**缺证据 ≠ 通过**（`INCOMPLETE` 排在 `FAIL` 之上，防止"删文件
绕过门禁"）。

在真实基准上，该链路把"naive 检查器 3/3 全绿 + 工具面 2/4 被 flag"改判为
`BLOCK`；在 11 维证据空间的全组合枚举（2304 原始组合 → 540 可行组合）中，只看
naive 的 240 个 PASS 组合里有 236 个（98.3%）被联合层降级，删证据不变量 0 违反。
在 53 个真实 MCP 工具上零误报，受控注入召回 73.7%（in-distribution）对 2.0%
（out-of-distribution）。真实模型评测（DeepSeek V4.1 Flash、GLM 5.3 Flash Max）
确认：naive 3/3 全绿在真实模型上**依旧不是通过信号**，但暴露的是检查器语言脆性
而非模型失实。

**边界**：样本量小（工具 4、题目 3、评测集 30），不构成能力声明；2% 与 73.7%
是两条独立测量路径的一致结果，但 50 条攻击载荷面向提示注入，属 out-of-
distribution 测试，不是原生攻击面检出率；规则是词法启发式，`FLAG` 只表示"值得
人工看一眼"。

## 关键结果（全部可复算）

| 指标 | 值 | 复算入口 |
|---|---|---|
| 联合裁决：假绿 + 工具命中 | `BLOCK`/R2 | `contracts/validate.py --all` |
| 决策组合枚举 | 2304 → 540 可行 | `scripts/joint_decision_matrix.py` |
| naive 240 个 PASS 被降级 | 236（98.3%） | 同上 |
| 删证据不变量违反 | 0 对 | 同上 |
| 真实 MCP 工具误报 | 0 / 53 | `scripts/scan_real_corpus.py` |
| in-distribution 召回 | 14/19 = 73.68% | `scripts/injected_recall.py` |
| out-of-distribution 召回 | 53/2650 = 2.00% | 同上 |
| 真实模型裁决变化 | BLOCK/R2 → REVIEW/R4 | `reports/2026-10-29-real-model-eval.md` |

## 与既有工作的关系

工具定义注入（tool poisoning）与评测结果操纵（eval overclaiming）在文献中常被
作为两个独立攻击面处理。本工作的区别不是提出新标准，而是把**同一套规则包的
配置驱动**与**缺证据即非通过**的裁决语义，做成零依赖、可复算、开源的自动化——
让"两个层各自正常"的组合失败能被机器抓到，而非依赖人工复核。

## 提交状态（诚实）

这是**工作论文摘要**，尚未投稿、未经过同行评审，也不是本仓的功能文档。它记录
本仓的实际贡献与边界，用于评估其研究价值。
