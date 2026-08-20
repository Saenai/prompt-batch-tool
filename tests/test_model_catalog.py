from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from prompt_batch.model_catalog import group_parameter_tiers, group_model_families, parse_llama_swap_models


class ModelGroupingTests(unittest.TestCase):
    def test_parses_sorted_config_directory_fragments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "20-b.yaml").write_text(
                'models:\n  model-b:\n    name: "Model B"\n    cmd: run-b\n', encoding="utf-8"
            )
            (root / "10-a.yml").write_text(
                "models:\n  model-a:\n    name: 'Model A'\n    cmd: run-a\n", encoding="utf-8"
            )
            (root / "ignored.txt").write_text("models:\n  ignored:\n", encoding="utf-8")

            self.assertEqual(
                parse_llama_swap_models(root),
                {"model-a": "Model A", "model-b": "Model B"},
            )

    def test_groups_by_configured_capture_and_respects_order(self) -> None:
        models = [
            ("other-7b-q4", "Other"),
            ("qwen3.6-27b-q5", "Qwen small"),
            ("gemma4-31b-q4", "Gemma"),
            ("qwen3.6-35b-q4", "Qwen large"),
        ]
        groups = group_model_families(models, {
            "pattern": r"^([^-]+)",
            "aliases": {"qwen3.6": "Qwen 3.6", "gemma4": "Gemma 4"},
            "order": ["gemma4", "qwen3.6"],
        })

        self.assertEqual([group.key for group in groups], ["gemma4", "qwen3.6", "other"])
        self.assertEqual([group.label for group in groups], ["Gemma 4", "Qwen 3.6", "other"])
        self.assertEqual(
            [model_id for model_id, _label in groups[1].models],
            ["qwen3.6-27b-q5", "qwen3.6-35b-q4"],
        )

    def test_unmatched_models_use_fallback_group(self) -> None:
        groups = group_model_families(
            [("standalone", "Standalone")],
            {
                "pattern": r"^(qwen)-",
                "fallback_group": "misc",
                "fallback_label": "未分类",
            },
        )
        self.assertEqual((groups[0].key, groups[0].label), ("misc", "未分类"))

    def test_invalid_pattern_has_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "grouping.pattern"):
            group_model_families([("model-a", "Model A")], {"pattern": "["})

    def test_parameter_tiers_sort_by_total_size_and_show_active_size(self) -> None:
        tiers = group_parameter_tiers(
            [
                ("gemma4-26b-a4b-q4", "Gemma MoE"),
                ("gemma4-31b-q4", "Gemma dense"),
                ("gemma4-custom", "Unknown"),
            ],
            {
                "pattern": r"(?:^|-)(\d+(?:\.\d+)?[bB])(?:-a(\d+(?:\.\d+)?[bB]))?(?:-|$)",
                "size_group": 1,
                "active_group": 2,
                "sort": "size-desc",
            },
        )
        self.assertEqual([tier.key for tier in tiers], ["31b", "26b-a4b", "unknown"])
        self.assertEqual([tier.label for tier in tiers], ["31B", "26B / A4B", "参数量未标注"])
        self.assertEqual(tiers[1].models[0][0], "gemma4-26b-a4b-q4")

    def test_parameter_tier_invalid_capture_has_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "捕获组"):
            group_parameter_tiers(
                [("model-7b", "Model")],
                {"pattern": r"(7b)", "size_group": 2},
            )

    def test_parameter_tiers_compare_units_numerically(self) -> None:
        tiers = group_parameter_tiers(
            [("model-500m", "Small"), ("model-7b", "Large")],
            {"pattern": r"(?:^|-)(\d+(?:\.\d+)?[mMbB])(?:-|$)"},
        )
        self.assertEqual([tier.key for tier in tiers], ["7b", "500m"])


if __name__ == "__main__":
    unittest.main()
