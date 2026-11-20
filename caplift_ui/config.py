"""Application configuration and path discovery for Caplift UI.

The UI expects ``lmstudio-caplift.exe`` to live in the same directory as the UI
executable. A local JSON config file, ``caplift_ui_config.json``, is stored next
to that executable so settings survive between runs (and so a portable install
can be moved as a folder).
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

APP_NAME = "Caplift UI"
CLI_EXE_NAME = "lmstudio-caplift.exe"
CONFIG_FILENAME = "caplift_ui_config.json"
DEFAULT_TIMEOUT_SECONDS = 300


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Directory holding the UI executable, or the project root in source mode."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    # caplift_ui/config.py -> project root is one level above the package
    return Path(__file__).resolve().parent.parent


def cli_candidates() -> List[Path]:
    """Places searched for the caplift CLI, most specific first.

    The same directory as the UI executable is authoritative; the parent
    directory is only a development convenience, because in the source tree the
    Rust executable sits one level above this Python package.
    """
    names = [CLI_EXE_NAME]
    if os.name != "nt":
        names.append("lmstudio-caplift")
    base = app_dir()
    candidates: List[Path] = []
    for name in names:
        candidates.append(base / name)
    for name in names:
        candidates.append(base.parent / name)
    return candidates


def find_cli(override: Optional[str] = None) -> Optional[Path]:
    """Return the path to the caplift executable, or None if it is missing.

    ``override`` (from the config file) wins when it points at a real file.
    """
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file():
            return candidate
    for candidate in cli_candidates():
        if candidate.is_file():
            return candidate
    return None


def config_path() -> Path:
    """Path of the local config file, next to the UI executable."""
    return app_dir() / CONFIG_FILENAME


def default_hub_models_dirs() -> List[Path]:
    """Where LM Studio keeps hub models when nothing is configured.

    The ``.cache`` shape is the older layout; both appear in the wild and the
    CLI treats the first as primary, so the order is meaningful.
    """
    home = Path.home()
    return [
        home / ".lmstudio" / "hub" / "models",
        home / ".cache" / "lm-studio" / "hub" / "models",
    ]


def hub_models_dir_candidates(configured: Optional[str] = None) -> List[Path]:
    """Directories to try, most authoritative first.

    A configured value wins outright — it is what gets passed to the CLI as
    ``--hub-models-dir``, so nothing else should be consulted.
    """
    if configured:
        return [Path(configured).expanduser()]
    return default_hub_models_dirs()


def resolve_hub_models_dir(configured: Optional[str] = None) -> Optional[Path]:
    """The hub models directory that actually exists, or None.

    Deliberately does not create anything or guess: callers use None to mean
    "cannot verify", which is different from "not there".
    """
    for candidate in hub_models_dir_candidates(configured):
        if candidate.is_dir():
            return candidate
    return None


@dataclass
class WindowConfig:
    width: int = 1200
    height: int = 780
    x: Optional[int] = None
    y: Optional[int] = None


@dataclass
class AppConfig:
    """User-facing settings persisted to ``caplift_ui_config.json``."""

    cli_path: Optional[str] = None
    hub_models_dir: Optional[str] = None
    lms_path: Optional[str] = None
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    use_huggingface: bool = False
    force_overwrite_by_default: bool = False
    window: WindowConfig = field(default_factory=WindowConfig)
    recent_base_templates: List[str] = field(default_factory=list)
    recent_hf_repos: List[str] = field(default_factory=list)

    # ---- serialisation -------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "AppConfig":
        data = data or {}
        window_raw = data.get("window") or {}
        if not isinstance(window_raw, dict):
            window_raw = {}
        window = WindowConfig(
            width=_as_int(window_raw.get("width"), 1200),
            height=_as_int(window_raw.get("height"), 780),
            x=_as_optional_int(window_raw.get("x")),
            y=_as_optional_int(window_raw.get("y")),
        )
        return cls(
            cli_path=_as_optional_str(data.get("cli_path")),
            hub_models_dir=_as_optional_str(data.get("hub_models_dir")),
            lms_path=_as_optional_str(data.get("lms_path")),
            timeout_seconds=_as_int(data.get("timeout_seconds"), DEFAULT_TIMEOUT_SECONDS),
            use_huggingface=bool(data.get("use_huggingface", False)),
            force_overwrite_by_default=bool(data.get("force_overwrite_by_default", False)),
            window=window,
            recent_base_templates=_as_str_list(data.get("recent_base_templates")),
            recent_hf_repos=_as_str_list(data.get("recent_hf_repos")),
        )

    # ---- convenience ---------------------------------------------------

    def remember(self, field_name: str, value: Optional[str], limit: int = 12) -> None:
        """Record a recently used value in one of the MRU lists."""
        if not value:
            return
        current = list(getattr(self, field_name))
        if value in current:
            current.remove(value)
        current.insert(0, value)
        setattr(self, field_name, current[:limit])


def _as_optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_optional_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any, fallback: int) -> int:
    parsed = _as_optional_int(value)
    return fallback if parsed is None else parsed


def _as_str_list(value: Any) -> List[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if str(item).strip()]


def load_config(path: Optional[Path] = None) -> AppConfig:
    """Load the config file, falling back to defaults when it is missing or broken."""
    target = path or config_path()
    try:
        raw = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return AppConfig()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return AppConfig()
    if not isinstance(data, dict):
        return AppConfig()
    return AppConfig.from_dict(data)


def save_config(config: AppConfig, path: Optional[Path] = None) -> Optional[str]:
    """Write the config file. Returns an error string on failure, otherwise None."""
    target = path or config_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(config.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        return f"Could not save {target}: {exc}"
    return None
