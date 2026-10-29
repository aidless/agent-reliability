# 攻击剧本覆盖率：agent-redteam × mcp-guard（M4）

**日期**：2026-10-28
**产物**：`reports/redteam-coverage-20261028.json`、`runs/20261028-r2-joint/redteam.json`
**复现**：

    cd ~/work/agent-reliability
    python3 scripts/redteam_coverage.py          # 打印两张表 + 写 reports/*.json

## 一句话结论

**50 条剧本样本里，工具面规则只能表达 1 条（2%）。** 这不是规则写坏了，而是
**两个层的攻击面几乎不相交**：mcp-guard 检查的是**工具定义投毒**，agent-redteam
的剧本是**提示注入 / 越狱 / 角色劫持 / 资源耗尽 / 聚合器捕获**——这些攻击不经过
工具描述这个入口。

## 方法

- 数据源：`aidless/agent-redteam` 的 `data/attack_vectors.json`
  （v0.1.0，50 条样本，12 个向量，Apache 2.0）。
- 判据：把每条 `payload` 过一遍 mcp-guard 的 `scan_text`；命中即"可表达"。
- 记录：命中的规则 id + 敏感锚点 + 命中片段；**不复制上游载荷**，只留判定结果。
- 溯源：`redteam_commit = 5ac6876a40ca1a965e6d21f722dc036aa19fb6b3`，`guard_commit = 13ae914f3e55644e2a0f70aed87746764ebf09f0`。

> **上游许可证不一致（照实记录）**：`data/attack_vectors.json` 的 metadata 写
> `"license": "Apache 2.0"`，而 agent-redteam 仓库根 `LICENSE` 是 MIT。
> 本仓**不复制载荷**，只记录派生判定（命中规则 / 锚点 / 长度），所以不受这一条影响；
> 但任何要复制该数据集的人必须先向上游确认以哪份为准。

## 表 1：按向量

| 向量 | 名称 | 样本 | 可表达 | 比例 |
|---|---|---:|---:|---:|
| `V01_direct_prompt_injection` | Direct Prompt Injection | 5 | 0 | 0.00 |
| `V02_indirect_prompt_injection` | Indirect Prompt Injection | 5 | 0 | 0.00 |
| `V03_jailbreak_templates` | Jailbreak Templates (DAN, etc.) | 6 | 0 | 0.00 |
| `V04_role_hijack` | Role / Persona Hijacking | 3 | 0 | 0.00 |
| `V05_tool_call_redirection` | Tool-Call Redirection | 5 | 1 | 0.20 |
| `V06_memory_poisoning` | Long-Term Memory Poisoning | 4 | 0 | 0.00 |
| `V07_output_exfiltration` | Output Exfiltration | 5 | 0 | 0.00 |
| `V08_aggregator_capture` | Aggregator / Verifier Capture | 3 | 0 | 0.00 |
| `V09_sybil_agent` | Sybil Agent Insertion | 2 | 0 | 0.00 |
| `V10_prompt_leakage` | System Prompt Leakage | 4 | 0 | 0.00 |
| `V11_resource_exhaustion` | Resource Exhaustion (DoS) | 4 | 0 | 0.00 |
| `V12_compositional` | Compositional Multi-Vector Attacks | 4 | 0 | 0.00 |

## 表 2：唯一被覆盖的那条

| 样本 | 向量 | 规则 | 锚点 | 命中片段 |
|---|---|---|---|---|
| `V05_004` | Tool-Call Redirection | `auth-url-exec` | `os.system` | `os.system(` |

`V05_004` 命中的是 `auth-url-exec`——因为它的载荷里直接写着 `os.system(...)`。
换句话说：**它被覆盖是因为载荷里出现了"工具参数直达 shell"的字样**，不是因为
平台理解了这个攻击。

## 这条覆盖率的准确含义（别读大）

**覆盖 = 「同一段文本如果出现在工具描述里，规则包会命中」。**
mcp-guard 坐在**工具定义**这一侧，不坐在**用户输入**这一侧。所以：

- ✅ 本表回答的是提案里的那个问题：剧本产出的每条攻击，能不能被工具面规则**表达**。
- ❌ **不等于**运行时会拦住这条攻击——位置不同，输入不同。
- ❌ **不等于**规则包对提示注入有效。2% 这个数字恰恰说明它对提示注入基本无效。

## 为什么这个低数字是有价值的

如果只报"我们接入了 redteam 剧本"而不报覆盖率，读者会以为平台对 12 类攻击都有防护。
实际是：**工具面这一层覆盖 1/50，剩下 49 条明确标为"规则不覆盖"**。

这直接约束了平台能声称什么：

| 平台能说 | 平台不能说 |
|---|---|
| "工具描述里的已知投毒模式会被规则命中" | "平台能防提示注入" |
| "漂移若改变了命中内容会被 R1 判 BLOCK" | "攻击剧本跑过了就说明系统安全" |
| "覆盖表列出了 49 条明确不覆盖的攻击" | "2% 覆盖率会被优化成 100%" |

## 接进平台的方式

- `run.py --redteam-repo <path>` 会写出 `runs/<run_id>/redteam.json`，
  并由 `contracts/redteam.schema.json` 校验（可选产物）。
- 证据里多三个字段：`attack_sim_present` / `attack_samples` / `attack_covered` /
  `attack_uncovered`。
- 规则 `R9-attack-layer-expresses-nothing`：只有在**一条都表达不了**时判 `REVIEW`。
  当前 1/50 **不触发**——覆盖率低是一个**常数事实**，写成每次都报警的规则只会制造噪音。
- 攻击剧本是**可选层**：没跑不会判 `INCOMPLETE`（`required_layers` 仍是
  输入面 + 输出面）。

## 这个实验**不能**说明什么

- 不能说明 mcp-guard 对真实 MCP server 的检出率（样本仍是自造的工具清单）。
- 不能说明 agent-redteam 的剧本是完备的（12 类覆盖不了所有攻击面）。
- 不能说明"2% 是上限"——规则包可以扩，但扩到能覆盖提示注入就等于把两种不同
  的检测器混成一种，代价是误报结构会变。
- 覆盖率随 `agent-redteam` 数据集版本变化；换版本必须重跑，不能沿用这个数字。
