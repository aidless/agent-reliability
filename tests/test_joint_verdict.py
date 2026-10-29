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
        "attack_sim_present": False,
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
        order = {"PASS": 0, "INCOMPLETE": 1, "REVIEW": 2, "FAIL": 3, "BLOCK": 4}
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
        """缺输出层 + 工具被 flag：REVIEW 更严重所以取它，但 R8 不能被吞掉。"""
        d = self.decide(tool_flagged=2, tool_clean=False, audit_present=False,
                        audit_rate=None, audit_rate_is_1=False,
                        audit_naive_all_green=None, audit_naive_green="",
                        missing_evidence_count=1)
        ids = [m["id"] for m in d["matched_rules"]]
        self.assertIn("R8-missing-evidence", ids)
        self.assertEqual(d["verdict"], "REVIEW")
        self.assertEqual(d["missing_evidence"], ["output_audit"])


class TestSchemaRejectsTampering(unittest.TestCase):
    """手改产物必须被契约层拦下——这是 M1 存在的全部理由。"""

    def test_baseline_instances_are_valid(self):
        """先确认基准样本本身合规，否则后面的"必须报错"没有意义。"""
        self.assertEqual(schema_errors(valid_meta(), "run.schema.json"), [])
        self.assertEqual(schema_errors(valid_tools(), "tool-evidence.schema.json"), [])
        self.assertEqual(schema_errors(valid_joint(), "joint-verdict.schema.json"), [])

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
        """r1 没有输出面证据：不能判成 PASS，缺哪层要写清楚。"""
        jv = self._joint("20261028-r1-baseline")
        self.assertNotEqual(jv["decision"]["verdict"], "PASS")
        self.assertEqual(jv["decision"]["missing_evidence"], ["output_audit"])
        ids = [m["id"] for m in jv["decision"]["matched_rules"]]
        self.assertIn("R8-missing-evidence", ids)

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
