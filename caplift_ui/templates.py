"""Discovering installed LM Studio Hub models that can serve as base templates.

A base template is a Hub model already installed under the hub models directory:
``lmstudio-caplift`` copies its ``manifest.json`` and ``model.yaml`` and rewrites
only the identity and base references. So the set of usable templates is exactly
the set of ``<hub models dir>/<owner>/<name>/`` directories that contain both
files — the same thing the CLI checks before it refuses to run.

Keeping this check in the UI means a typo is caught before the CLI is invoked,
rather than surfacing as a one-line error after a subprocess round trip.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

MANIFEST_NAME = "manifest.json"
MODEL_YAML_NAME = "model.yaml"

# caplift writes its wrappers under this namespace, which is how a wrapper is
# told apart from an official Hub model.
WRAPPER_OWNER = "local"


@dataclass(frozen=True)
class BaseTemplate:
    """One installed Hub model that can be copied from."""

    model_id: str
    path: Path

    @property
    def is_wrapper(self) -> bool:
        """True for a wrapper caplift itself created, not an official model.

        Wrappers are copyable but make poor templates — and using one as both
        template and wrapper id would write into that model's own folder.
        """
        return self.model_id.split("/", 1)[0] == WRAPPER_OWNER


@dataclass(frozen=True)
class TemplateCheck:
    """Result of checking one candidate id against the hub models directory."""

    model_id: str
    # False when no hub models directory could be located, so the id is neither
    # confirmed nor denied. Callers must not treat this as "missing".
    checked: bool
    found: bool
    hub_dir: Optional[Path] = None
    path: Optional[Path] = None
    reason: str = ""


def looks_like_model_id(value: str) -> bool:
    """True for ``owner/name`` with exactly one slash and no blanks."""
    parts = [part for part in value.strip().split("/") if part.strip()]
    return len(parts) == 2


def find_installed_templates(hub_dir: Optional[Path]) -> List[BaseTemplate]:
    """List installed Hub models that have both required files.

    Official models are returned before wrappers, each group sorted, because
    official models are the ones worth copying from.
    """
    if hub_dir is None or not hub_dir.is_dir():
        return []

    templates: List[BaseTemplate] = []
    try:
        owner_dirs = sorted(entry for entry in hub_dir.iterdir() if entry.is_dir())
    except OSError:
        return []

    for owner_dir in owner_dirs:
        if owner_dir.name.startswith("."):
            continue
        try:
            name_dirs = sorted(entry for entry in owner_dir.iterdir() if entry.is_dir())
        except OSError:
            continue
        for name_dir in name_dirs:
            has_manifest = (name_dir / MANIFEST_NAME).is_file()
            has_model_yaml = (name_dir / MODEL_YAML_NAME).is_file()
            if has_manifest and has_model_yaml:
                templates.append(BaseTemplate(f"{owner_dir.name}/{name_dir.name}", name_dir))

    templates.sort(key=lambda template: (template.is_wrapper, template.model_id))
    return templates


def check_template(hub_dir: Optional[Path], model_id: str) -> TemplateCheck:
    """Check whether ``model_id`` is a usable base template.

    Mirrors the CLI's own test — the directory must exist and contain both
    files — so the UI can refuse the same cases the CLI would.
    """
    value = (model_id or "").strip()
    if not value:
        return TemplateCheck(value, checked=True, found=False, reason="No base template set.")
    if not looks_like_model_id(value):
        return TemplateCheck(
            value,
            checked=True,
            found=False,
            reason="Base template should look like owner/name, e.g. qwen/qwen3.8-27b.",
        )
    if hub_dir is None:
        return TemplateCheck(value, checked=False, found=False)

    path = hub_dir.joinpath(*value.split("/"))
    if not path.is_dir():
        return TemplateCheck(
            value,
            checked=True,
            found=False,
            hub_dir=hub_dir,
            path=path,
            reason=(
                f"Not installed at {path}. Install it from LM Studio's Hub, "
                "or pick one of the models you already have."
            ),
        )

    missing = [
        name
        for name in (MANIFEST_NAME, MODEL_YAML_NAME)
        if not (path / name).is_file()
    ]
    if missing:
        return TemplateCheck(
            value,
            checked=True,
            found=False,
            hub_dir=hub_dir,
            path=path,
            reason=(
                f"{path} exists but has no {', '.join(missing)}, so it cannot be "
                "copied from."
            ),
        )

    return TemplateCheck(value, checked=True, found=True, hub_dir=hub_dir, path=path)
