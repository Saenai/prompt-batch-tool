from __future__ import annotations

import unittest

from prompt_batch.model_source import group_models


class ModelGroupingTests(unittest.TestCase):
    def test_groups_by_configured_capture_and_respects_order(self) -> None:
        models = [
            ("other-7b-q4", "Other"),
            ("qwen3.6-27b-q5", "Qwen small"),
            ("gemma4-31b-q4", "Gemma"),
            ("qwen3.6-35b-q4", "Qwen large"),
        ]
        groups = group_models(models, {
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
        groups = group_models(
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
            group_models([("model-a", "Model A")], {"pattern": "["})


if __name__ == "__main__":
    unittest.main()
