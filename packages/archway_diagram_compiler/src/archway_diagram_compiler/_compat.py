"""Compatibility helpers for supported Pydantic versions."""

from typing import Any


def copy_model(model: Any, **kwargs: Any) -> Any:
    if hasattr(model, "model_copy"):
        return model.model_copy(**kwargs)
    return model.copy(**kwargs)
