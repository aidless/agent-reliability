#!/usr/bin/env python3
"""联合裁决与契约层的测试（M1 契约层 + M2 联合裁决层）。

跑法（从项目根目录 ~/work/agent-reliability）：
    python3 -m unittest discover -s tests -v
    python3 tests/test_joint_verdict.py -v

五组覆盖：
    TestRulesContract           规则文件（数据）自身自洽
    TestDecisionCombos          裁决分级的全部组合
    TestSchemaRejectsTampering  手改产物必须被契约层拦下
    TestSchemaCrossValidation   与参照实现 jsonschema 逐条比对结论
    TestRealRuns                真实 run 产物过契约；手改裁决必须被抓出
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"
RUNS = ROOT / "runs"

sys.path.insert(0, str(CONTRACTS))
sys.path.insert(0, str(ROOT / "rules"))

import engine  # noqa: E402
from jsonschema_mini import validate  # noqa: E402

# contracts/validate.py 叫 validate，和 jsonschema_mini 里的函数同名。
# 用 importlib 按文件路径显式装载，避免和上面的函数撞名。
_spec = importlib.util.spec_from_file_location(
    "contract_validator", CONTRACTS / "validate.py")
contract_validator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(contract_validator)


def load_schema(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def schema_errors(instance: dict, schema_name: str) -> list[str]:
    return validate(instance, load_schema(schema_name))


def valid_meta() -> dict:
    """一份满足 run.schema.json 的 meta。"""
    return {
        "run_id": "test-run",
        "created_utc": "2026-10-28T12:00:00+00:00",
        "rules_version": "0123456789abcdef",
        "scorer_version": "fedcba9876543210",
        "tool_digests": {"get_weather": "d" * 64},
        "repos": {
            "mcp-guard": {"path": "/tmp/mcp-guard", "commit": "a" * 40},
            "auditable-llm-eval": {"path": "/tmp/auditable-llm-eval", "commit": "b" * 40},
        },
        "tools_input": "/tmp/tools.json",
    }


def valid_tools() -> dict:
    """一份满足 tool-evidence.schema.json 的工具面证据。"""
    return {
        "run_id": "test-run",
        "rules_version": "0123456789abcdef",
        "scanned": 1,
        "flagged": 0,
        "baseline_run": None,
        "tools": [
            {
                "name": "get_weather",
                "digest": "c" * 64,
                "flagged": False,
                "hits": [],
                "drift": {"status": "no-baseline", "fields": [], "new_hits": []},
                "definition": {
                    "name": "get_weather",
                    "description": "Get current weather for a city.",
                    "inputSchema": {"type": "object", "properties": {}},
                },
            }
        ],
    }


def valid_joint() -> dict:
    """一份满足 joint-verdict.schema.json 的联合裁决。"""
    return {
        "run_id": "test-run",
        "input_guard": {
            "scanned": 1,
            "flagged": 0,
            "flagged_tools": [],
            "drift_alerts": [],
            "verdict": "CLEAN",
        },
        "decision": {
            "verdict": "PASS",
            "severity": "info",
            "rule_id": None,
            "why": "合成样本",
            "matched_rules": [],
            "evidence": {},
            "missing_evidence": [],
            "rules_version": "0123456789abcdef",
        },
    }


def valid_redteam() -> dict:
    """一份满足 redteam.schema.json 的覆盖率表。"""
    return {
        "run_id": "test-run",
        "redteam_commit": "e" * 40,
        "dataset_version": "0.1.0",
        "dataset_license": "Apache 2.0",
        "total_samples": 2,
        "covered": 1,
        "uncovered": 1,
        "coverage_rate": 0.5,
        "interpretation": "覆盖 = 该载荷若出现在工具描述里会被规则命中。",
        "by_vector": [
            {"vector_id": "V01", "vector_name": "x", "category": "input_attack",
             "samples": 2, "covered": 1, "rate": 0.5},
        ],
        "samples": [
            {"sample_id": "V01_001", "vector_id": "V01", "covered": True,
             "rules": ["secret-read"], "anchors": ["ssh"]},
            {"sample_id": "V01_002", "vector_id": "V01", "covered": False,
             "rules": [], "anchors": []},
        ],
    }


def evidence(**over) -> dict:
    """基准证据：工具面干净 + 输出面满分。用关键字参数改写需要变化的字段。"""
    base = {
        "tool_scanned": 4,
        "tool_flagged": 0,
        "tool_flagged_names": [],
        "tool_drift_alerts": 0,
        "tool_drift_new_hits": 0,
        "tool_drift_changed_hits": 0,
        "tool_drift_alarm": 0,
        "tool_drift_unknown": 0,
        "tool_clean": True,
        "audit_present": True,
        "audit_total": 3,
        "audit_semantic_scored": 3,
        "audit_excluded": 0,
        "audit_runtime_errors": 0,
        "audit_rate": 1.0,
        "audit_rate_is_1": True,
        "audit_naive_all_green": True,
        "audit_naive_green": "3/3",
        "audit_unsupported_claims": 0,
        "missing_evidence_count": 0,
        "output_evidence_regressed": False,
        "attack_sim_present": False,
        "attack_samples": 0,
        "attack_covered": 0,
        "attack_uncovered": 0,
    }
    base.update(over)
    # 与 derive_evidence 同一条规则：alarm 由 new_hits / changed_hits 推出来。
    # 显式传了就以传入值为准（用于测"产物字段与推导不一致"的场景）。
    if "tool_drift_alarm" not in over:
        base["tool_drift_alarm"] = 1 if (
            base["tool_drift_new_hits"] or base["tool_drift_changed_hits"]) else 0
    if over.get("missing_evidence_count", 0) > 0:
        base.setdefault("_missing_evidence", ["output_audit"])
    return base


class TestRulesContract(unittest.TestCase):
    """规则是数据。这里保证这份数据没写坏——改判据只改 JSON，不改 engine。"""

    @classmethod
    def setUpClass(cls):
        cls.rules = engine.load_rules()
        cls.declared = set(cls.rules["evidence_fields"])

    def test_rule_ids_unique(self):
        ids = [r["id"] for r in self.rules["rules"]]
        self.assertEqual(len(ids), len(set(ids)), f"规则 id 重复：{ids}")

    def test_rule_ids_have_prefix(self):
        for rule in self.rules["rules"]:
            self.assertRegex(rule["id"], r"^R\d+-",
                             f"规则 id 应带 R<数字>- 前缀，便于排序与引用：{rule['id']}")

    def test_condition_fields_are_declared(self):
        for rule in self.rules["rules"]:
            for cond in rule.get("all", []):
                self.assertIn(cond["field"], self.declared,
                              f"{rule['id']} 用了未在 evidence_fields 声明的字段 {cond['field']}")

    def test_declared_fields_are_actually_produced(self):
        """evidence_fields 声明的每个字段，derive_evidence 都必须真的产出。"""
        with tempfile.TemporaryDirectory() as tmp:
            ev = engine.derive_evidence(pathlib.Path(tmp), self.rules)
        produced = {k for k in ev if not k.startswith("_")}
        self.assertEqual(
            self.declared, produced,
            "evidence_fields 与 derive_evidence 的产出字段不一致："
            f"声明了但没产出 {sorted(self.declared - produced)}；"
            f"产出了但没声明 {sorted(produced - self.declared)}")

    def test_verdict_within_precedence(self):
        prec = set(self.rules["verdict_precedence"])
        for rule in self.rules["rules"]:
            self.assertIn(rule["verdict"], prec,
                          f"{rule['id']} 的 verdict {rule['verdict']} 不在 verdict_precedence 内")

    def test_operators_are_legal(self):
        legal = {"eq", "ne", "gt", "gte", "lt", "lte", "nonempty", "empty", "in", "contains"}
        for rule in self.rules["rules"]:
            for cond in rule.get("all", []):
                self.assertIn("field", cond, f"{rule['id']} 的条件缺 field")
                self.assertIn(cond.get("op", "eq"), legal,
                              f"{rule['id']} 用了未知操作符 {cond.get('op')!r}")

    def test_precedence_is_strictly_ordered(self):
        """precedence 必须从最严重排到最轻，引擎取第一个命中即为最严重者。"""
        prec = self.rules["verdict_precedence"]
        self.assertEqual(len(prec), len(set(prec)), "verdict_precedence 里有重复")
        # INCOMPLETE 排在 FAIL 之上：删掉证据不能把 FAIL 变轻（否则门禁可被
        # "删输出面文件"绕过），但 BLOCK 仍然最高。
        order = {"PASS": 0, "REVIEW": 1, "FAIL": 2, "INCOMPLETE": 3, "BLOCK": 4}
        vals = [order[v] for v in prec]
        self.assertEqual(vals, sorted(vals, reverse=True),
                         f"verdict_precedence 必须从最严重排到最轻：{prec}")

    def test_required_layers_non_empty(self):
        self.assertTrue(self.rules["required_layers"], "required_layers 不能为空")


class TestDecisionCombos(unittest.TestCase):
    """裁决分级的全部组合：什么证据 → 什么结论。"""

    @classmethod
    def setUpClass(cls):
        cls.rules = engine.load_rules()

    def decide(self, **over) -> dict:
        return engine.evaluate(self.rules, evidence(**over))

    def test_clean_tools_and_perfect_output_passes(self):
        d = self.decide()
        self.assertEqual(d["verdict"], "PASS")
        self.assertIsNone(d["rule_id"])
        self.assertEqual(d["matched_rules"], [])

    def test_flagged_tools_with_perfect_output_reviews(self):
        d = self.decide(tool_flagged=2, tool_clean=False,
                        tool_flagged_names=["export_profile"])
        self.assertEqual(d["verdict"], "REVIEW")
        self.assertEqual(d["rule_id"], "R4-flagged-tools")

    def test_flagged_tools_with_false_green_blocks(self):
        d = self.decide(tool_flagged=2, tool_clean=False,
                        audit_rate=0.6667, audit_rate_is_1=False)
        self.assertEqual(d["verdict"], "BLOCK")
        self.assertEqual(d["rule_id"], "R2-false-green-over-untrusted-tools")

    def test_clean_tools_with_false_green_fails(self):
        d = self.decide(audit_rate=0.6667, audit_rate_is_1=False)
        self.assertEqual(d["verdict"], "FAIL")
        self.assertEqual(d["rule_id"], "R3-false-green")

    def test_missing_output_layer_is_incomplete_not_pass(self):
        d = self.decide(audit_present=False, audit_rate=None, audit_rate_is_1=False,
                        audit_naive_all_green=None, audit_naive_green="",
                        missing_evidence_count=1)
        self.assertEqual(d["verdict"], "INCOMPLETE")
        self.assertEqual(d["rule_id"], "R8-missing-evidence")
        self.assertEqual(d["missing_evidence"], ["output_audit"])
        self.assertNotEqual(d["verdict"], "PASS", "缺证据绝不能判成 PASS")

    def test_drift_with_new_rule_blocks(self):
        """全新规则开始触发 = 告警级。"""
        d = self.decide(tool_drift_alerts=1, tool_drift_new_hits=1, tool_clean=False)
        self.assertEqual(d["verdict"], "BLOCK")
        self.assertEqual(d["rule_id"], "R1-drift-with-hit-change")

    def test_drift_with_payload_swap_blocks(self):
        """载荷替换：没有新规则，但同一规则命中的东西换了。

        这是旧实现（规则 id 集合差集）看不见的那一类：new_hits 为空，
        changed_hits 非空，必须仍然判 BLOCK。
        """
        d = self.decide(tool_drift_alerts=1, tool_drift_new_hits=0,
                        tool_drift_changed_hits=1, tool_drift_alarm=1,
                        tool_clean=False)
        self.assertEqual(d["verdict"], "BLOCK")
        self.assertEqual(d["rule_id"], "R1-drift-with-hit-change")

    def test_drift_without_hit_change_reviews(self):
        """只是措辞变了、命中内容没变：REVIEW，不是 BLOCK。"""
        d = self.decide(tool_drift_alerts=1, tool_clean=False)
        self.assertEqual(d["verdict"], "REVIEW")
        self.assertEqual(d["rule_id"], "R5-drift")

    def test_audit_coverage_gap_reviews(self):
        """runtime_error 把题排除掉，汇总分的分母变小了——必须能被看见。"""
        d = self.decide(audit_excluded=2, audit_total=5, audit_semantic_scored=3)
        self.assertEqual(d["verdict"], "REVIEW")
        self.assertEqual(d["rule_id"], "R6-audit-coverage-gap")

    def test_attack_layer_expressing_nothing_reviews(self):
        """跑过剧本但一条都表达不了：不能拿这一层的"干净"当"攻击已被覆盖"。"""
        d = self.decide(attack_sim_present=True, attack_samples=50,
                        attack_covered=0, attack_uncovered=50)
        self.assertEqual(d["verdict"], "REVIEW")
        self.assertEqual(d["rule_id"], "R9-attack-layer-expresses-nothing")

    def test_attack_layer_with_some_coverage_does_not_review(self):
        """有覆盖就不触发 R9——覆盖率低本身是常数事实，不该每次 run 都报警。"""
        d = self.decide(attack_sim_present=True, attack_samples=50,
                        attack_covered=1, attack_uncovered=49)
        self.assertEqual(d["verdict"], "PASS")
        self.assertIsNone(d["rule_id"])

    def test_missing_attack_layer_is_not_incomplete(self):
        """攻击剧本是可选层：没跑不该判 INCOMPLETE。"""
        d = self.decide(attack_sim_present=False)
        self.assertEqual(d["verdict"], "PASS")
        self.assertEqual(d["missing_evidence"], [])

    def test_all_matched_rules_are_reported(self):
        """全部命中的规则都要上报——"为什么不是 PASS"必须可追溯。"""
        d = self.decide(tool_flagged=2, tool_clean=False,
                        audit_rate=0.6667, audit_rate_is_1=False)
        ids = [m["id"] for m in d["matched_rules"]]
        self.assertEqual(ids, [
            "R2-false-green-over-untrusted-tools",
            "R4-flagged-tools",
            "R7-audit-not-perfect",
        ])
        for m in d["matched_rules"]:
            for key in ("id", "verdict", "severity", "why"):
                self.assertIn(key, m)
            self.assertTrue(m["why"].strip(), f"{m['id']} 缺解释")

    def test_most_severe_verdict_wins(self):
        """R2(BLOCK) 与 R7(FAIL) 同时命中时，取更严重的 BLOCK。"""
        d = self.decide(tool_flagged=2, tool_clean=False,
                        audit_rate=0.6667, audit_rate_is_1=False)
        verdicts = {m["id"]: m["verdict"] for m in d["matched_rules"]}
        self.assertEqual(verdicts["R7-audit-not-perfect"], "FAIL")
        self.assertEqual(d["verdict"], "BLOCK")

    def test_missing_evidence_survives_alongside_other_rules(self):
        """缺输出层 + 工具被 flag：INCOMPLETE 更严重，但 R4 不能被吞掉。"""
        d = self.decide(tool_flagged=2, tool_clean=False, audit_present=False,
                        audit_rate=None, audit_rate_is_1=False,
                        audit_naive_all_green=None, audit_naive_green="",
                        missing_evidence_count=1)
        ids = [m["id"] for m in d["matched_rules"]]
        self.assertIn("R4-flagged-tools", ids)
        self.assertIn("R8-missing-evidence", ids)
        self.assertEqual(d["verdict"], "INCOMPLETE")
        self.assertEqual(d["missing_evidence"], ["output_audit"])

    def test_deleting_output_evidence_never_lightens_the_verdict(self):
        """删掉输出面不能把 FAIL 变轻——否则 {BLOCK, FAIL} 门禁可被"删文件"绕过。

        这条不变量是 2026-10-28 用全组合枚举测出来的：当时 INCOMPLETE 排在
        FAIL 之下，删掉 audit/ 就让 severity 3 → 1。
        """
        sev = {"PASS": 0, "REVIEW": 1, "FAIL": 2, "INCOMPLETE": 3, "BLOCK": 4}
        with_audit = self.decide(audit_rate=0.6667, audit_rate_is_1=False,
                                 audit_naive_all_green=False)
        without_audit = self.decide(audit_present=False, audit_rate=None,
                                    audit_rate_is_1=False,
                                    audit_naive_all_green=None, audit_naive_green="",
                                    missing_evidence_count=1)
        self.assertEqual(with_audit["verdict"], "FAIL")
        self.assertEqual(without_audit["verdict"], "INCOMPLETE")
        self.assertGreaterEqual(
            sev[without_audit["verdict"]], sev[with_audit["verdict"]],
            "删掉输出面证据后裁决变轻了")

    def test_output_evidence_regression_blocks(self):
        """上一轮有输出面、这一轮没有 = 证据被删，必须 BLOCK。

        没有这条时，删掉 audit/ 会连带消掉 R2（假绿 BLOCK），
        裁决从 BLOCK 掉到 INCOMPLETE——门禁按 {BLOCK, FAIL} 判定就被绕过了。
        """
        d = self.decide(audit_present=False, audit_rate=None, audit_rate_is_1=False,
                        audit_naive_all_green=None, audit_naive_green="",
                        missing_evidence_count=1,
                        output_evidence_regressed=True)
        self.assertEqual(d["verdict"], "BLOCK")
        self.assertEqual(d["rule_id"], "R10-output-evidence-regressed")
        ids = [m["id"] for m in d["matched_rules"]]
        self.assertIn("R8-missing-evidence", ids)

    def test_evidence_regression_needs_a_baseline(self):
        """没有基线时不能凭空判 R10——只在"上一轮有、这一轮没有"时才成立。"""
        d = self.decide(audit_present=False, audit_rate=None, audit_rate_is_1=False,
                        audit_naive_all_green=None, audit_naive_green="",
                        missing_evidence_count=1,
                        output_evidence_regressed=False)
        self.assertEqual(d["verdict"], "INCOMPLETE")
        self.assertEqual(d["rule_id"], "R8-missing-evidence")


class TestEvidenceRegression(unittest.TestCase):
    """证据回退的判定必须来自**真实目录**，不能只靠合成字段。

    `derive_evidence` 会去看上一轮 run 里有没有 `audit/summary.json`；
    这条路径只有构造出一对 run 目录才能覆盖（`M2-engine-regression-never-detected`
    这个变异就是靠它被抓的）。
    """

    @staticmethod
    def _tools_json(baseline_run: str | None) -> str:
        return json.dumps({
            "run_id": "cur",
            "rules_version": "0" * 16,
            "scanned": 0,
            "flagged": 0,
            "baseline_run": baseline_run,
            "tools": [],
        })

    def test_missing_audit_after_a_baseline_that_had_one_is_a_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = pathlib.Path(tmp)
            base = runs / "base"
            (base / "audit").mkdir(parents=True)
            (base / "audit" / "summary.json").write_text("{}", encoding="utf-8")

            cur = runs / "cur"
            cur.mkdir()
            (cur / "tools.json").write_text(self._tools_json("base"), encoding="utf-8")

            ev = engine.derive_evidence(cur)
            self.assertTrue(ev["output_evidence_regressed"])
            self.assertEqual(ev["missing_evidence_count"], 1)

    def test_missing_audit_without_such_a_baseline_is_not_a_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = pathlib.Path(tmp)
            base = runs / "base"
            base.mkdir()                      # 基线自己也没有输出面
            cur = runs / "cur"
            cur.mkdir()
            (cur / "tools.json").write_text(self._tools_json("base"), encoding="utf-8")
            ev = engine.derive_evidence(cur)
            self.assertFalse(ev["output_evidence_regressed"])

    def test_first_run_has_no_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            cur = pathlib.Path(tmp) / "cur"
            cur.mkdir()
            (cur / "tools.json").write_text(self._tools_json(None), encoding="utf-8")
            ev = engine.derive_evidence(cur)
            self.assertFalse(ev["output_evidence_regressed"])


class TestSchemaRejectsTampering(unittest.TestCase):
    """手改产物必须被契约层拦下——这是 M1 存在的全部理由。"""

    def test_baseline_instances_are_valid(self):
        """先确认基准样本本身合规，否则后面的"必须报错"没有意义。"""
        self.assertEqual(schema_errors(valid_meta(), "run.schema.json"), [])
        self.assertEqual(schema_errors(valid_tools(), "tool-evidence.schema.json"), [])
        self.assertEqual(schema_errors(valid_joint(), "joint-verdict.schema.json"), [])
        self.assertEqual(schema_errors(valid_redteam(), "redteam.schema.json"), [])

    def test_missing_required_field_is_rejected(self):
        bad = valid_meta()
        del bad["rules_version"]
        errs = schema_errors(bad, "run.schema.json")
        self.assertTrue(errs, "删掉必填字段竟然没报错")
        self.assertTrue(
            any("缺少必填字段" in e and "rules_version" in e for e in errs), errs)

    def test_bad_digest_pattern_is_rejected(self):
        bad = valid_tools()
        bad["tools"][0]["digest"] = "NOT-A-SHA256"
        errs = schema_errors(bad, "tool-evidence.schema.json")
        self.assertTrue(any("pattern" in e for e in errs), errs)

    def test_undeclared_field_is_rejected(self):
        bad = valid_meta()
        bad["surprise"] = 1
        errs = schema_errors(bad, "run.schema.json")
        self.assertTrue(any("未声明字段" in e for e in errs), errs)

    def test_bad_rules_version_is_rejected(self):
        bad = valid_meta()
        bad["rules_version"] = "NOTHEX"
        errs = schema_errors(bad, "run.schema.json")
        self.assertTrue(any("rules_version" in e for e in errs), errs)

    def test_bad_scorer_version_is_rejected(self):
        bad = valid_meta()
        bad["scorer_version"] = "NOTHEX"
        errs = schema_errors(bad, "run.schema.json")
        self.assertTrue(any("scorer_version" in e for e in errs), errs)

    def test_bad_commit_is_rejected(self):
        bad = valid_meta()
        bad["repos"]["mcp-guard"]["commit"] = "deadbeef"
        errs = schema_errors(bad, "run.schema.json")
        self.assertTrue(any("commit" in e for e in errs), errs)

    def test_unknown_verdict_is_rejected(self):
        bad = valid_joint()
        bad["decision"]["verdict"] = "MAYBE"
        errs = schema_errors(bad, "joint-verdict.schema.json")
        self.assertTrue(any("MAYBE" in e for e in errs), errs)

    def test_decision_missing_required_field_is_rejected(self):
        bad = valid_joint()
        del bad["decision"]["matched_rules"]
        errs = schema_errors(bad, "joint-verdict.schema.json")
        self.assertTrue(any("matched_rules" in e for e in errs), errs)

    def test_impossible_coverage_rate_is_rejected(self):
        bad = valid_redteam()
        bad["coverage_rate"] = 1.5
        errs = schema_errors(bad, "redteam.schema.json")
        self.assertTrue(any("coverage_rate" in e for e in errs), errs)

    def test_redteam_missing_commit_is_rejected(self):
        bad = valid_redteam()
        del bad["redteam_commit"]
        errs = schema_errors(bad, "redteam.schema.json")
        self.assertTrue(any("redteam_commit" in e for e in errs), errs)


class TestSchemaCrossValidation(unittest.TestCase):
    """零依赖校验器 vs 参照实现 jsonschema——两边结论必须一致。"""

    @classmethod
    def setUpClass(cls):
        try:
            from jsonschema import Draft7Validator
        except ImportError:
            cls.validator_cls = None
        else:
            cls.validator_cls = Draft7Validator

    def test_cross_validation(self):
        if self.validator_cls is None:
            self.skipTest("环境里没有装 jsonschema，参照实现不可用")

        bad_meta = valid_meta()
        del bad_meta["tool_digests"]

        bad_joint = valid_joint()
        bad_joint["decision"]["severity"] = "catastrophic"

        bad_tools = valid_tools()
        bad_tools["tools"][0]["digest"] = "zzz"

        cases = [
            ("run.schema.json", valid_meta(), True),
            ("run.schema.json", bad_meta, False),
            ("tool-evidence.schema.json", valid_tools(), True),
            ("tool-evidence.schema.json", bad_tools, False),
            ("joint-verdict.schema.json", valid_joint(), True),
            ("joint-verdict.schema.json", bad_joint, False),
        ]
        for schema_name, instance, expected_ok in cases:
            with self.subTest(schema=schema_name, expected_ok=expected_ok):
                mine_ok = not schema_errors(instance, schema_name)
                ref_errors = list(
                    self.validator_cls(load_schema(schema_name)).iter_errors(instance))
                self.assertEqual(mine_ok, expected_ok,
                                 f"本实现的判定与预期不符：{schema_name}")
                self.assertEqual(mine_ok, not ref_errors,
                                 f"本实现与参照实现 jsonschema 结论不一致：{schema_name}")


class TestRealCorpus(unittest.TestCase):
    """真实 MCP 工具定义语料 + 扫描结果的回归锁。

    语料由 `scripts/collect_mcp_tools.py` 采集（真实 `tools/list`），
    扫描由 `scripts/scan_real_corpus.py` 产出。这里只锁结构一致性——
    不重新跑 mcp-guard，所以 `gates` job 不需要上游仓。
    """

    CORPUS = ROOT / "corpus" / "mcp-tools-20261028.json"
    SCAN = ROOT / "reports" / "real-mcp-scan-20261028.json"

    def test_corpus_is_structurally_sound(self):
        corpus = json.loads(self.CORPUS.read_text(encoding="utf-8"))
        self.assertEqual(len(corpus["servers"]), 6)
        self.assertEqual(corpus["failures"], [])
        for server in corpus["servers"]:
            self.assertEqual(server["tool_count"], len(server["tools"]),
                             f"{server['server_id']} 的 tool_count 与 tools 长度不符")
            for tool in server["tools"]:
                self.assertTrue(tool["name"], "工具必须有名字")
        self.assertEqual(corpus["total_tools"],
                         sum(s["tool_count"] for s in corpus["servers"]))

    def test_real_benign_tools_are_not_flagged(self):
        """53 个真实良性工具必须零误报；这条红了就说明规则包开始误伤真实工具。"""
        scan = json.loads(self.SCAN.read_text(encoding="utf-8"))
        corpus = json.loads(self.CORPUS.read_text(encoding="utf-8"))
        self.assertEqual(scan["corpus_file"], self.CORPUS.name)
        self.assertEqual(scan["total_tools"], corpus["total_tools"])
        self.assertEqual(scan["flagged_tools"], 0,
                         f"真实语料上出现误报：{scan['rule_counts']}")
        self.assertEqual(sum(s["flagged"] for s in scan["per_server"]), 0)


class TestRealRuns(unittest.TestCase):
    """真实 run 产物：必须过契约；手改裁决必须被抓出来。"""

    def setUp(self):
        self.run_dirs = sorted(
            p for p in RUNS.iterdir()
            if p.is_dir() and not p.name.startswith("_")
        )

    def _joint(self, run_id: str) -> dict:
        path = RUNS / run_id / "joint_verdict.json"
        self.assertTrue(path.exists(), f"缺少产物 {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_there_are_runs(self):
        self.assertTrue(self.run_dirs, "runs/ 下没有产物，先跑 python3 run.py")

    def test_all_real_runs_pass_contract(self):
        for d in self.run_dirs:
            with self.subTest(run=d.name):
                problems = contract_validator.check_run(d)
                self.assertEqual(problems, [], "\n".join(problems))

    def test_cli_validate_all_passes(self):
        proc = subprocess.run(
            [sys.executable, str(CONTRACTS / "validate.py"), "--all"],
            capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_r2_joint_is_blocked(self):
        """假绿 + 工具被 flag = BLOCK，这是平台存在的理由。"""
        jv = self._joint("20261028-r2-joint")
        self.assertEqual(jv["decision"]["verdict"], "BLOCK")
        self.assertEqual(jv["decision"]["rule_id"], "R2-false-green-over-untrusted-tools")

    def test_r3_drift_is_visible(self):
        """载荷替换必须由 R1 直接判 BLOCK，而不是只靠 R2 兜底。"""
        jv = self._joint("20261028-r3-drift")
        ids = [m["id"] for m in jv["decision"]["matched_rules"]]
        self.assertIn("R5-drift", ids, "漂移没有出现在 matched_rules 里")
        self.assertIn("R1-drift-with-hit-change", ids,
                      "载荷替换没有触发 R1——new_hits 又退回规则 id 级别了吗？")
        self.assertEqual(jv["decision"]["rule_id"], "R1-drift-with-hit-change")
        self.assertEqual(jv["decision"]["evidence"]["tool_drift_alerts"], 1)
        self.assertEqual(jv["decision"]["evidence"]["tool_drift_changed_hits"], 1)

    def test_missing_output_layer_is_not_pass(self):
        """r1 没有输出面证据：判 INCOMPLETE，且缺哪层要写清楚。"""
        jv = self._joint("20261028-r1-baseline")
        self.assertEqual(jv["decision"]["verdict"], "INCOMPLETE")
        self.assertEqual(jv["decision"]["rule_id"], "R8-missing-evidence")
        self.assertEqual(jv["decision"]["missing_evidence"], ["output_audit"])
        ids = [m["id"] for m in jv["decision"]["matched_rules"]]
        self.assertIn("R8-missing-evidence", ids)

    def test_redteam_coverage_is_recorded(self):
        """M4：跑过攻击剧本时，覆盖率必须落在产物里，且被标为"可表达"。"""
        run = RUNS / "20261028-r2-joint"
        path = run / "redteam.json"
        self.assertTrue(path.exists(), "缺少 redteam.json")
        rt = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(rt["total_samples"], len(rt["samples"]))
        self.assertEqual(rt["covered"] + rt["uncovered"], rt["total_samples"])
        self.assertEqual(len(rt["by_vector"]), 12)
        self.assertRegex(rt["redteam_commit"], r"^[0-9a-f]{40}$")

        jv = self._joint("20261028-r2-joint")
        e = jv["decision"]["evidence"]
        self.assertTrue(e["attack_sim_present"])
        self.assertEqual(e["attack_samples"], rt["total_samples"])
        self.assertEqual(e["attack_covered"], rt["covered"])

    def test_tampered_decision_is_caught(self):
        """手改 verdict 放水，必须被 validate.py 抓出来。"""
        src = RUNS / "20261028-r2-joint"
        with tempfile.TemporaryDirectory() as tmp:
            dst = pathlib.Path(tmp) / src.name
            shutil.copytree(src, dst)
            jv_path = dst / "joint_verdict.json"
            jv = json.loads(jv_path.read_text(encoding="utf-8"))
            jv["decision"]["verdict"] = "PASS"
            jv["decision"]["severity"] = "info"
            jv["decision"]["rule_id"] = None
            jv_path.write_text(
                json.dumps(jv, ensure_ascii=False, indent=2), encoding="utf-8")

            problems = contract_validator.check_run(dst)
            self.assertTrue(problems, "手改 verdict 竟然没被抓出来")
            self.assertTrue(
                any("decision.verdict" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main(verbosity=2)
