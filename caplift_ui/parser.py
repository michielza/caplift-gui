"""Tolerant parsers for ``lmstudio-caplift`` output.

The CLI emits JSON for ``list --json``. The exact key set is owned by the Rust
side, so every lookup here is alias-tolerant and returns partial data rather
than raising: a UI that shows "unknown" beats a UI that crashes when the CLI
gains or renames a field.

Observed ``list --all --json`` shape (captured from lmstudio-caplift)::

    {
      "availableModels": [
        {
          "architecture": "granite",
          "defaultWrapperModelId": "local/granite-4-2-30b",
          "displayName": "Granite 4.2 30B",
          "modelKey": "granite-4.2-30b",
          "paramsString": "30B",
          "path": "lmstudio-community/granite-4.2-30b-GGUF/granite-4.2-30b-Q4_K_M.gguf",
          "publisher": "lmstudio-community",
          "selectedBaseModelId": null
        }
      ],
      "wrappedModels": [
        {
          "baseModelId": "meta/muse-glimmer",
          "createdAtUnixSeconds": 1795206747,
          "modelKey": "owner/repo/file.gguf",
          "targetDir": "C:/Users/example/.lmstudio/hub/models/local/name",
          "updatedAtUnixSeconds": 1795206747,
          "wrapperModelId": "local/name"
        }
      ]
    }

Note the asymmetry that matters: available models carry
``defaultWrapperModelId``/``selectedBaseModelId``, while wrapped models carry
``wrapperModelId``/``baseModelId``. ``tests/fixtures/list_all.json`` is a real
capture, so a schema change in the CLI shows up as a test failure.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .models import AvailableModel, RegistryView, WrappedModel

# Keys we accept for each logical field, in priority order.
_MODEL_KEY_ALIASES = ("modelKey", "model_key", "key", "model", "name")
_WRAPPER_ID_ALIASES = (
    # "defaultWrapperModelId" is what `list --all --json` actually emits for
    # available models; the rest are tolerated older/alternate spellings.
    "defaultWrapperModelId",
    "wrapperModelId",
    "wrapper_model_id",
    "suggestedWrapperModelId",
    "wrapperModel",
    "wrapper",
)
_BASE_ID_ALIASES = (
    # "selectedBaseModelId" is the real key for available models and is null
    # when the conservative matcher declines to pick a template.
    "selectedBaseModelId",
    "baseModelId",
    "base_model_id",
    "selectedBaseTemplateId",
    "baseTemplateId",
    "baseTemplate",
    "baseModelKey",
    "template",
    "base",
)
_TARGET_DIR_ALIASES = ("targetDir", "targetDirectory", "target_dir", "outputDir")
_CREATED_ALIASES = ("createdAtUnixSeconds", "createdAt", "created_at", "created")
_UPDATED_ALIASES = ("updatedAtUnixSeconds", "updatedAt", "updated_at", "updated")
_HF_REPO_ALIASES = ("hfRepo", "hf_repo", "huggingfaceRepo", "repo")
_DISPLAY_NAME_ALIASES = ("displayName", "display_name", "name")
_PUBLISHER_ALIASES = ("publisher", "owner")
_PARAMS_ALIASES = ("paramsString", "params_string", "params")
_ARCHITECTURE_ALIASES = ("architecture", "arch")
_PATH_ALIASES = ("path", "modelPath")

# Values the CLI uses to mean "no defensible static match".
_NA_VALUES = {"", "n/a", "na", "none", "null", "unknown", "-"}


class ParseError(ValueError):
    """Raised when output cannot be interpreted at all."""


def _pick(source: Mapping[str, Any], aliases: Iterable[str]) -> Optional[Any]:
    for alias in aliases:
        if alias in source:
            value = source[alias]
            if value is not None:
                return value
    return None


def _clean_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in _NA_VALUES:
        return None
    return text


def _clean_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _iter_entries(value: Any) -> List[Tuple[Optional[str], Mapping[str, Any]]]:
    """Yield ``(container_key, entry)`` pairs, tolerating several shapes.

    A list yields ``(None, entry)``. A mapping keyed by model id yields its key
    as well, so that key can stand in for a missing ``modelKey`` — the CLI is
    the authority on what a row is called, and a dictionary key is one of its
    own.

    Only entries that are themselves objects are yielded. Coercing a scalar or
    ``null`` to an empty mapping would not be harmless here: paired with its
    container key, an empty mapping still produces a row, so ``{"x": null}``
    would invent a model called ``x``. A value that is not an object carries no
    identity and is skipped.
    """
    entries: List[Tuple[Optional[str], Mapping[str, Any]]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, Mapping):
                entries.append((None, item))
        return entries
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(item, Mapping):
                entries.append((None if key is None else str(key), item))
        return entries
    return []


def parse_registry_json(text: str) -> RegistryView:
    """Parse ``list --json`` output into a :class:`RegistryView`."""
    stripped = (text or "").strip()
    if not stripped:
        return RegistryView()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ParseError(f"Could not read JSON from lmstudio-caplift: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ParseError("Expected a JSON object from lmstudio-caplift list --json")

    available_raw = _pick(payload, ("availableModels", "available", "available_models"))
    wrapped_raw = _pick(payload, ("wrappedModels", "wrapped", "wrapped_models", "tracked"))

    available: List[AvailableModel] = []
    for container_key, entry in _iter_entries(available_raw):
        model_key = _clean_str(_pick(entry, _MODEL_KEY_ALIASES)) or _clean_str(
            container_key
        )
        if not model_key:
            # No usable identifier anywhere. The base-template field is NOT a
            # fallback: it names the capability profile to copy, not the model
            # being wrapped, so taking it as the model key would hand ``wrap``
            # an id that resolves to a template. A row without an identity is
            # dropped rather than given a plausible-but-wrong one.
            continue
        available.append(
            AvailableModel(
                model_key=model_key,
                wrapper_model_id=_clean_str(_pick(entry, _WRAPPER_ID_ALIASES)),
                base_model_id=_clean_str(_pick(entry, _BASE_ID_ALIASES)),
                hf_repo=_clean_str(_pick(entry, _HF_REPO_ALIASES)),
                display_name=_clean_str(_pick(entry, _DISPLAY_NAME_ALIASES)),
                publisher=_clean_str(_pick(entry, _PUBLISHER_ALIASES)),
                params_string=_clean_str(_pick(entry, _PARAMS_ALIASES)),
                architecture=_clean_str(_pick(entry, _ARCHITECTURE_ALIASES)),
                path=_clean_str(_pick(entry, _PATH_ALIASES)),
                raw=entry,
            )
        )

    wrapped: List[WrappedModel] = []
    for container_key, entry in _iter_entries(wrapped_raw):
        wrapper_id = _clean_str(_pick(entry, _WRAPPER_ID_ALIASES)) or _clean_str(
            container_key
        )
        # No container-key fallback for the source key here, unlike the
        # available loop: in a registry keyed by id, a wrapped entry's key is
        # the *wrapper's* own id, so adopting it would have Repair claim the
        # wrapper wraps itself. Left None so ``has_source_key`` withholds
        # Repair instead of guessing.
        model_key = _clean_str(_pick(entry, _MODEL_KEY_ALIASES))
        if not wrapper_id and not model_key:
            continue
        wrapped.append(
            WrappedModel(
                wrapper_model_id=wrapper_id or "(unknown)",
                model_key=model_key,
                base_model_id=_clean_str(_pick(entry, _BASE_ID_ALIASES)),
                target_dir=_clean_str(_pick(entry, _TARGET_DIR_ALIASES)),
                created_at_unix_seconds=_clean_int(_pick(entry, _CREATED_ALIASES)),
                updated_at_unix_seconds=_clean_int(_pick(entry, _UPDATED_ALIASES)),
                raw=entry,
            )
        )

    return RegistryView(available=tuple(available), wrapped=tuple(wrapped))


# --------------------------------------------------------------------------
# Dry-run preview
# --------------------------------------------------------------------------

_HEADER_KEYS = {
    "wrapper": "wrapper_model_id",
    "model key": "model_key",
    "base template": "base_model_id",
    "target directory": "target_dir",
    "registry": "registry_path",
}
_FILE_SECTION_RE = re.compile(r"^---\s+(?P<path>.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class DryRunPreview:
    """Parsed ``wrap --dry-run`` output."""

    wrapper_model_id: Optional[str] = None
    model_key: Optional[str] = None
    base_model_id: Optional[str] = None
    target_dir: Optional[str] = None
    registry_path: Optional[str] = None
    files: Tuple[Tuple[str, str], ...] = ()
    raw_text: str = ""
    header: Mapping[str, Any] = field(default_factory=dict)

    @property
    def file_names(self) -> Tuple[str, ...]:
        return tuple(path.replace("\\", "/").rsplit("/", 1)[-1] for path, _ in self.files)


def parse_dry_run(text: str) -> DryRunPreview:
    """Parse the output of ``wrap ... --dry-run``.

    The format is a small header of ``Key: value`` lines, then one section per
    generated file introduced by ``--- <absolute path>``.
    """
    raw = text or ""
    sections = list(_FILE_SECTION_RE.finditer(raw))
    header_text = raw[: sections[0].start()] if sections else raw

    header: Dict[str, Any] = {}
    for line in header_text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        normalised = key.strip().lower()
        if normalised in _HEADER_KEYS:
            header[_HEADER_KEYS[normalised]] = value.strip()

    files: List[Tuple[str, str]] = []
    for index, match in enumerate(sections):
        path = match.group("path").strip()
        start = match.end()
        end = sections[index + 1].start() if index + 1 < len(sections) else len(raw)
        body = raw[start:end].strip("\n")
        files.append((path, body))

    return DryRunPreview(
        wrapper_model_id=_clean_str(header.get("wrapper_model_id")),
        model_key=_clean_str(header.get("model_key")),
        base_model_id=_clean_str(header.get("base_model_id")),
        target_dir=_clean_str(header.get("target_dir")),
        registry_path=_clean_str(header.get("registry_path")),
        files=tuple(files),
        raw_text=raw,
        header=header,
    )


# --------------------------------------------------------------------------
# Error message helpers
# --------------------------------------------------------------------------

_MISSING_BASE_RE = re.compile(
    r"no suitable static base template found for (?P<model>.+?);\s*pass --base-model-id",
    re.IGNORECASE,
)
# Emitted when the field is left blank, so the CLI chooses a template itself and
# then finds it is not installed. Distinct from the case above: there the CLI
# declined to choose, here it chose badly.
_BASE_NOT_INSTALLED_RE = re.compile(
    r"base template (?P<template>\S+) is not installed at (?P<path>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_LMS_UNAVAILABLE_HINTS = (
    "no running lm studio",
    "failed to start or connect",
    "no valid installation was found",
)


def describe_cli_error(stderr: str, stdout: str = "") -> str:
    """Turn raw CLI error output into one human-readable sentence."""
    combined = f"{stderr}\n{stdout}".strip()
    if not combined:
        return "lmstudio-caplift exited with an error but printed no message."

    lowered = combined.lower()
    if any(hint in lowered for hint in _LMS_UNAVAILABLE_HINTS):
        return (
            "LM Studio is not running and no installation could be reached, so the "
            "installed-model list is unavailable. Start LM Studio (or the `lms` "
            "service) and refresh."
        )

    match = _MISSING_BASE_RE.search(combined)
    if match:
        return (
            f"No static base template matched {match.group('model').strip()}. "
            "Set one explicitly in the Base template field (--base-model-id for the CLI), "
            "for example `qwen/qwen3.5-35b-a3b` for a Qwen3.5 model, then wrap again."
        )

    match = _BASE_NOT_INSTALLED_RE.search(combined)
    if match:
        template = match.group("template").strip()
        return (
            f"The base template field was left empty, so lmstudio-caplift chose `{template}` "
            f"itself — but that model is not installed at {match.group('path').strip()}. "
            "Pick an installed template from the Base template field, or install "
            f"`{template}` from LM Studio's Hub."
        )

    first_error = next(
        (line.strip() for line in combined.splitlines() if line.strip().lower().startswith("error")),
        None,
    )
    return first_error or combined.splitlines()[0].strip()
