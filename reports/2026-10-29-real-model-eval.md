# 真实模型输出上的假绿测量（第一次）

**日期**：2026-10-29
**产物**：`runs/20261029-r4…r7/`、`config/joint_eval_predictions.real-*.jsonl`（模型原文）
**复现**：

    cd ~/work/agent-reliability
    python3 scripts/run_real_model_eval.py --model raccoon/sn-deepseek-v4-1-flash
    python3 run.py --tools config/tools.example.json \
      --dataset config/joint_eval_dataset.jsonl \
      --predictions config/joint_eval_predictions.real-raccoon-sn-deepseek-v4-1-flash.jsonl \
      --predictions-model raccoon/sn-deepseek-v4-1-flash \
      --baseline-run 20261028-r2-joint --run-id rerun-deepseek

## 为什么做

在此之前 `config/joint_eval_predictions.jsonl` 的 3 条输出是**手写的**，
「auditable 抓假绿」只在构造数据上成立。这是第一次用真实模型的输出跑同一条链路。

模型走本机已配置的 OpenAI 兼容网关（`temperature=0`，每模型 3 次调用，零边际成本——
额度来自已配置的订阅，未新增任何付费）；产物记录 `predictions_model`，
`scorer_version` 与之分开，两边的「变了」从此都能定位。

## 结果总表

| 模型 | 严格关键词 权威分 | 双语容错 权威分 | 裁决（严格） | 裁决（双语） |
|---|---:|---:|---|---|
['| DeepSeek V4.1 Flash | `raccoon/sn-deepseek-v4-1-flash` | 0.8333 | 1.0000 | `BLOCK`/R2 | `REVIEW`/R4 |', '| GLM 5.3 Flash Max | `trae-cn/glm-5.3-flash-max` | 0.8889 | 1.0000 | `BLOCK`/R2 | `REVIEW`/R4 |']

**两个模型、两种数据集，naive 检查器都是 3/3 全绿**——真实模型上假绿依旧存在，
与手写数据时代的结论一致。

## 关键发现：挂掉的不是模型，是检查器

两个模型都只挂在 `must_include_all_keywords` 上，而且都是**写了正确的中文**：

| 模型 | 题 | 检查器要 | 模型写的 | 判定 |
|---|---|---|---|---|
| DeepSeek | c902 | `timeout` | 「超时」 | 0.5（错误地扣分） |
| GLM | c903 | `metrics` | 「指标」 | 0.6667（错误地扣分） |

把这两条检查改成中英任一（`['timeout','超时']`、`['metrics','指标','度量']`）后，
**两个模型的权威分都从 <1.0 回到 1.0**。

这不是给模型「放水」：c902 的题面问的是诊断（模型按题面要求用中文答），检查器却
要求答案里出现英文 `timeout`——**语言不匹配是检查器的缺陷，不是模型的失实**。
但必须诚实地说：改成 any-of 也确实放宽了约束（原来要求同时出现两个英文词，
现在每个位置任选一个表述），这个放宽是**有意识的、记录在案的**。

## 对裁决的直接影响

| | 严格关键词 | 双语容错 |
|---|---|---|
| DeepSeek | `BLOCK`/R2（工具有命中 + 假绿） | `REVIEW`/R4 |
| GLM | `BLOCK`/R2 | `REVIEW`/R4 |

**同一条链路上，检查器的一个语言缺陷能把裁决从 `BLOCK` 拉到 `REVIEW`。**
这正好演示了联合裁决层的设计初衷：工具面的命中（R4）独立于输出面的评分存在，
评分修好后结论随之回到「工具面需要人工复核」这个**真实状态**——
而不是被一个假绿信号带着跑。

## 对手写时代的数字意味着什么

| 数据 | naive | 权威分 | 读法 |
|---|---|---|---|
| 手写（c901 明确过度宣称） | 3/3 | 0.6667 | **真实的假绿**：模型行为确实失实 |
| 真实模型（DeepSeek/GLM） | 3/3 | 0.83–0.89 | **检查器脆性**：模型没失实，检查器语言错配 |

两个数字都真实，但**成因不同**。旧数据的 0.6667 里有一部分也是检查器脆性
（c902 的 52 字中文答案被 runtime 护栏吃掉，D6 已记录）——真实模型实验把这一点
从「怀疑」变成了「证实」。

## 能说明什么

- ✅ naive 全绿在**真实模型**上依旧不是通过信号（两个模型 3/3 全绿，权威分 <1.0）。
- ✅ 检查器脆性对裁决有**直接、可量化的影响**：一个语言缺陷 = `BLOCK`→`REVIEW`。
- ✅ `predictions_model` + `scorer_version` 两个字段让「谁变了」可定位。

## 不能说明什么

- ❌ 每模型只 3 题、2 个模型：不构成任何模型质量比较，也不构成通过率估计。
- ❌ 双语容错的「1.0」是在**放宽后的检查**下的 1.0，与原检查的 1.0 不是一个口径。
- ❌ 没测「模型会不会真的过度宣称」——那需要让模型面对**诱导性**的题面，
  这批题面是中性的。
- ❌ 免费网关额度随时可能变化；本报告的模型可用性只在 2026-10-29 成立。

## 下一步

- 把双语容错版定为主数据集（严格版保留为 `joint_eval_dataset.jsonl`，两者都在仓里）。
- c901 的「过度宣称」检测在真实模型上没有复现机会——下一个实验应该用**诱导性题面**
  看真实模型会不会宣称 tamper-proof，那才是「auditable 抓假绿」的完全体。
