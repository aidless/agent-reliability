#!/usr/bin/env python3
"""真实模型 runner 的离线参数与路径测试。"""
from __future__ import annotations

import importlib.util
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "real_model_runner", ROOT / "scripts" / "run_real_model_eval.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class TestOutputPaths(unittest.TestCase):
    def test_dataset_stem_keeps_experiments_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = pathlib.Path(tmp) / "induced_overclaim_dataset.jsonl"
            output = runner.default_output_path(
                pathlib.Path(tmp), dataset, "raccoon/sn-deepseek-v4-1-flash")
        self.assertEqual(
            output.name,
            "induced_overclaim_predictions.real-raccoon-sn-deepseek-v4-1-flash.jsonl",
        )

    def test_explicit_output_is_preserved(self):
        explicit = pathlib.Path("/tmp/custom.jsonl")
        self.assertEqual(
            runner.resolve_output_path(
                pathlib.Path("/repo"), pathlib.Path("/repo/config/data.jsonl"),
                "model/id", explicit),
            explicit,
        )


if __name__ == "__main__":
    unittest.main()
