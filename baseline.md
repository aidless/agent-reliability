# 基线快照（D1）

**采集时间**：2026-10-28（America/Los_Angeles） / 原始输出：[`reports/baseline-20261028.txt`](./reports/baseline-20261028.txt)
**环境**：Linux，Python 3.12.3，pytest 9.1.1
**两个 checkout**（D1 采集时的状态）：

- `~/mcp-guard` @ `08e3c9876c69e48ca384921ae976d47e614b6e42`（= 远端 main，未漂移）
- `~/auditable-llm-eval` @ `11d8f3890441c785a5ceb60c0da8286d028760c2`（= 远端 main）

> **2026-10-28 晚**：两仓各追加了提交（mcp-guard `56aac4d` → `13ae914`、
> auditable-llm-eval `f7e00d2`），**均已 push 到 GitHub 的 main**。上表保留 D1
> 采集时的状态作为历史；现在 `runs/*/meta.json` 记录的是 `13ae914` 与 `f7e00d2`。

## 每个数字 + 它的复算命令

| 数字 | 复算命令 | 输出 |
|---|---|---|
| mcp-guard 测试 16 passed | `cd ~/mcp-guard && python3 -m pytest tests/ -q` | `16 passed` |
| mcp-guard 规则指标 | `cd ~/mcp-guard && python3 run_eval.py --offline` | `n_poison 19 / n_benign 11 / recall_case 0.7368 / fpr_benign 0.0 / recall_rule 0.7083` |
| auditable 单测 40 | `cd ~/auditable-llm-eval && python3 -m unittest discover -s tests` | `Ran 40 tests ... OK` |
| auditable pytest 40 | `cd ~/auditable-llm-eval && python3 -m pytest tests -q` | `40 passed` |
| 发布门禁 4/4 | `cd ~/auditable-llm-eval && python3 scripts/validate_release.py` | `selftest/spec/verifier/gitignore` 全 PASS，`OVERALL: PASS` |
| 假绿落差 32 点 | `cd ~/auditable-llm-eval && python3 demo.py` | `0.67 (match=True)` / `0.69 (match=True)` / `32 points` |
| 联合判决 | `cd ~/work/agent-reliability && python3 run.py --tools config/tools.example.json --dataset config/joint_eval_dataset.jsonl --predictions config/joint_eval_predictions.jsonl --run-id rerun` | `input_guard=FLAG(2/4)`、`output_audit=0.6667`、`naive=3/3`、`gap=33.3` |

## M1 / M2 追加（2026-10-28 续做）

| 数字 | 复算命令 | 输出 |
|---|---|---|
| 平台层测试 51 | `cd ~/work/agent-reliability && python3 -m unittest discover -s tests` | `Ran 51 tests ... OK` |
| 契约校验 3 个 run | `cd ~/work/agent-reliability && python3 contracts/validate.py --all` | `20261028-r1-baseline OK`、`r2-joint OK`、`r3-drift OK`，`全部通过（3 个 run）` |
| 变异控制 14/14 抓到 | `cd ~/work/agent-reliability && python3 scripts/mutation_control.py` | `全部 14 个变异都被测试抓到（测试有牙齿）。` |
| 攻击剧本覆盖率 | `cd ~/work/agent-reliability && python3 scripts/redteam_coverage.py --quiet` | `covered 1 / total 50`，`coverage_rate 0.02`（V05_004 命中 `auth-url-exec`） |
| 敏感锚点不变量 | `cd ~/mcp-guard && python3 -m pytest tests/ -q` | `23 passed`（含 3 个无害改写 `alarm=False`、3 个真换载荷 `alarm=True`、80 字符截断不受影响） |
| 决策函数全组合 | `cd ~/work/agent-reliability && python3 scripts/joint_decision_matrix.py` | `可行 540 / 原始 2304`；naive 基线降级 `236/240 = 0.9833`；权威基线 `232/240 = 0.9667`；删证据违反 `0` 对（无基线不可知 12 对） |
| 真实模型假绿 | 查 `runs/20261029-r4-real-deepseek/joint_verdict.json` 的 `decision.verdict` 与 `output_audit.{naive_green,authoritative_rate}` | `BLOCK, 3/3, 0.8333`（GLM 同构 `BLOCK, 3/3, 0.8889`）；双语容错后两模型 `REVIEW` + 权威 `1.0` |
| 受控注入召回 | `cd ~/work/agent-reliability && python3 scripts/injected_recall.py --redteam-repo ~/agent-redteam` | in-dist `14/19 = 0.7368`；OOD `53/2650 = 0.02`（append/prepend/replace 三者相同）；基线 `0/53`、良性对照 `0/53` |
| 真实 MCP 语料误报 | `cd ~/work/agent-reliability && python3 scripts/scan_real_corpus.py --fail-if-flagged` | `6 个 server / 53 个工具，被 flag 0 = 0.0`（零误报） |
| 评分器版本 | `cd ~/work/agent-reliability && python3 -c "import json;print(json.load(open('runs/20261028-r2-joint/meta.json'))['scorer_version'])"` | `62b240b797547d69`（`copilot/score_copilot_run_v2.py` 的 sha256 前 16 位） |
| 联合裁决 r2 | `cd ~/work/agent-reliability && python3 -c "import json;d=json.load(open('runs/20261028-r2-joint/joint_verdict.json'));print(d['decision']['verdict'],d['decision']['rule_id'])"` | `BLOCK R2-false-green-over-untrusted-tools` |
| 联合裁决 r1（缺输出层） | 同上，换 `runs/20261028-r1-baseline` | `INCOMPLETE R8-missing-evidence`（R4 同时命中，`missing_evidence=["output_audit"]`） |
| 联合裁决 r3（漂移） | 同上，换 `runs/20261028-r3-drift` | `BLOCK R1-drift-with-hit-change`（`new_hits` 仍为空，但 `changed_hits=["secret-read"]`，R1 因此触发） |

## 重建整条 run 链（确定性复现）

基线**显式指定**，结论就不取决于 `runs/` 里还躺着什么别的目录：

    cd ~/work/agent-reliability

    python3 run.py --tools config/tools.example.json \
      --no-baseline --run-id 20261028-r1-baseline

    python3 run.py --tools config/tools.example.json \
      --dataset config/joint_eval_dataset.jsonl \
      --predictions config/joint_eval_predictions.jsonl \
      --baseline-run 20261028-r1-baseline --run-id 20261028-r2-joint

    python3 run.py --tools config/tools.drifted.json \
      --dataset config/joint_eval_dataset.jsonl \
      --predictions config/joint_eval_predictions.jsonl \
      --baseline-run 20261028-r2-joint --run-id 20261028-r3-drift

实测：连跑两遍，除 `created_utc` 外逐字段一致；从 `meta.json` 记录的两个 commit
（mcp-guard `56aac4d`、auditable-llm-eval `f7e00d2`）**干净导出**后重跑，三个裁决
与 `runs/` 里的完全一致。

## 口径说明（避免把数字读大）

- `recall_case 0.7368` = **19 条毒用例上**的检出率，不是总体检出率。
- `fpr_benign 0.0` = **11 条良性用例上**的零误报，不是"通用零误报"。
- `recall_rule 0.7083` = gold 规则命中率（17/24）。
- auditable 的 `32 points` = 100% naive green 与两个权威分均值（0.68）之差；
  联合实验里的 `33.3 points` 是 3 题小样本下的同类指标，**与 32 points 不是同一个统计量**。
- 评测集只有 30 条、工具只有 4 个、题目只有 3 道——**全部数字只用于回归锁定，不作能力声明**。
- 裁决只有 10 条规则（R1–R10），是为这批 4 工具 / 3 题样例写的；**没有在真实语料上
  验证过召回率**。`INCOMPLETE` 排在 `FAIL` 之上是刻意的：删掉 `audit/` 会把 `FAIL`
  变成 `INCOMPLETE`，如果 `INCOMPLETE` 更轻，按 `{BLOCK, FAIL}` 判定的门禁就能被
  「删文件」绕过（2026-10-28 用全组合枚举测出并修正）。
- `73.68%` 是 **in-distribution**（规则照着写的 19 条毒用例），`2.00%` 是 **out-of-distribution**（50 条公开提示注入载荷塞进 53 个真实工具）。两个数不可相加、不可只报一个。
- `changed_hits` 比的是 `(规则 id, 命中文本)`，命中文本由 `scan_text` 截断到 80 字符。
  理论上存在"改在 80 字符之后"的漏报——当前未构造出该用例，属已知未验证边界。
