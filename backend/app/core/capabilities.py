# -*- coding: utf-8 -*-
"""Capability labels derived from work that actually completed in a request."""
from __future__ import annotations


MODEL_MODES = {"model", "model_rules_review", "model_grounded", "model_unreviewed"}


def combine_capability_modes(*modes: str | None) -> str:
    """Combine specialist capabilities without promoting missing work to model mode."""
    values = list(dict.fromkeys(str(mode).strip() for mode in modes if mode))
    if not values:
        return "unavailable"

    has_model = any(mode in MODEL_MODES or mode.startswith("model_") for mode in values)
    has_local = any(mode.startswith("local_") for mode in values)
    has_unavailable = "unavailable" in values
    has_unreviewed = any(mode.endswith("_unreviewed") for mode in values)

    if has_unreviewed:
        return "model_unreviewed" if has_model else (
            "local_unreviewed" if has_local else "unavailable"
        )
    if has_unavailable:
        return "model_partial" if has_model else (
            "local_partial" if has_local else "unavailable"
        )
    if has_model and has_local:
        return "model_grounded"
    if has_model:
        return values[0] if len(values) == 1 else "model"
    if has_local:
        return values[0] if len(values) == 1 else "local_grounded"
    return "unavailable"
