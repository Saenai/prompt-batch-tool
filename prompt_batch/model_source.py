"""Backward-compatible aliases for the renamed model catalog module."""

from .model_catalog import (
    ModelFamily,
    ModelGroup,
    ModelTier,
    ParameterTier,
    discover_models,
    fetch_model_ids,
    group_model_families,
    group_model_tiers,
    group_models,
    group_parameter_tiers,
    parse_llama_swap_models,
)

__all__ = [
    "ModelFamily",
    "ModelGroup",
    "ModelTier",
    "ParameterTier",
    "discover_models",
    "fetch_model_ids",
    "group_model_families",
    "group_model_tiers",
    "group_models",
    "group_parameter_tiers",
    "parse_llama_swap_models",
]
