"""Data model for models reported by ``lmstudio-caplift``."""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional


_DOTS = re.compile(r"\.")


def derive_wrapper_id(model_key: str) -> str:
    """Best-effort guess at the wrapper id the CLI would derive.

    Only a fallback for when the CLI omits ``defaultWrapperModelId``. Observed
    convention: lowercase, with dots turned into dashes — ``granite-4.2-30b``
    becomes ``local/granite-4-2-30b``.
    """
    parts = [segment for segment in model_key.split("/") if segment]
    if len(parts) >= 3:
        stem = parts[-2]  # owner/repo/quant.gguf -> repo
    elif len(parts) == 2:
        stem = parts[-1]
    elif parts:
        stem = parts[0]
    else:
        stem = model_key
    if stem.lower().endswith(".gguf"):
        stem = stem[: -len(".gguf")]
    stem = re.sub(r"\s+", "-", stem.strip())
    stem = _DOTS.sub("-", stem).lower()
    return f"local/{stem}"


def format_unix_seconds(value: Optional[int]) -> str:
    """Render a unix timestamp as local time, or a dash when unknown."""
    if not value:
        return "—"
    try:
        moment = _dt.datetime.fromtimestamp(int(value))
    except (OverflowError, OSError, ValueError):
        return "—"
    return moment.strftime("%Y-%m-%d %H:%M")


@dataclass(frozen=True)
class AvailableModel:
    """An installed LLM that is not tracked as a wrapper yet."""

    model_key: str
    wrapper_model_id: Optional[str] = None
    base_model_id: Optional[str] = None
    hf_repo: Optional[str] = None
    display_name: Optional[str] = None
    publisher: Optional[str] = None
    params_string: Optional[str] = None
    architecture: Optional[str] = None
    path: Optional[str] = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def suggested_wrapper_id(self) -> str:
        """The CLI's own default when provided, else a local derivation."""
        return self.wrapper_model_id or derive_wrapper_id(self.model_key)

    @property
    def has_base_template(self) -> bool:
        return bool(self.base_model_id)

    @property
    def summary(self) -> str:
        """One-line description built from whatever metadata is present."""
        bits = [self.publisher, self.params_string, self.architecture]
        return " · ".join(bit for bit in bits if bit)


@dataclass(frozen=True)
class WrappedModel:
    """A wrapper tracked in the CLI's own registry."""

    wrapper_model_id: str
    model_key: str
    base_model_id: Optional[str] = None
    target_dir: Optional[str] = None
    created_at_unix_seconds: Optional[int] = None
    updated_at_unix_seconds: Optional[int] = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def created_display(self) -> str:
        return format_unix_seconds(self.created_at_unix_seconds)

    @property
    def updated_display(self) -> str:
        return format_unix_seconds(self.updated_at_unix_seconds)

    @property
    def target_path(self) -> Optional[Path]:
        if not self.target_dir:
            return None
        return Path(self.target_dir)


@dataclass(frozen=True)
class RegistryView:
    """Parsed result of ``list --json``."""

    available: tuple[AvailableModel, ...] = ()
    wrapped: tuple[WrappedModel, ...] = ()

    @property
    def available_count(self) -> int:
        return len(self.available)

    @property
    def wrapped_count(self) -> int:
        return len(self.wrapped)
