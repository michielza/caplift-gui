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
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

APP_NAME = "Caplift UI"
CLI_EXE_NAME = "lmstudio-caplift.exe"
CONFIG_FILENAME = "caplift_ui_config.json"
DEFAULT_TIMEOUT_SECONDS = 300

# The one place the timeout bounds live. The Settings form, the config loader
# and the runner all clamp to these, so a stored value and the value actually
# used cannot disagree. Previously the loader stored whatever was in the file
# and only the runner clamped, so Settings could show 99999 while the CLI was
# given 3600.
MIN_TIMEOUT_SECONDS = 5
MAX_TIMEOUT_SECONDS = 3600

# Serialises the rename step of save_config. See the note there: concurrent
# os.replace calls onto one destination fail on Windows rather than racing
# cleanly, so saves are ordered.
_SAVE_LOCK = threading.Lock()


def sane_timeout(value: Any) -> int:
    """Clamp ``value`` to the supported range, falling back when unusable.

    ``OverflowError`` is caught alongside the usual two: JSON has no limit on
    exponent size, so a settings file containing ``1e309`` loads as
    ``float("inf")`` and ``int()`` of that raises. A number we cannot represent
    is an unusable value like any other, and must not crash startup.
    """
    # bool is an int subclass, and int(True) is 1 — a timeout of five seconds,
    # not a value anyone stored on purpose.
    if isinstance(value, bool):
        return DEFAULT_TIMEOUT_SECONDS
    if isinstance(value, float) and (
        value != value or value in (float("inf"), float("-inf"))
    ):
        return DEFAULT_TIMEOUT_SECONDS
    try:
        parsed = int(value) if value is not None else DEFAULT_TIMEOUT_SECONDS
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_TIMEOUT_SECONDS
    return max(MIN_TIMEOUT_SECONDS, min(parsed, MAX_TIMEOUT_SECONDS))


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
            # Clamped on the way in, not just on the way out, so the number
            # shown in Settings is the number the runner will use.
            timeout_seconds=sane_timeout(data.get("timeout_seconds")),
            use_huggingface=_as_bool(data.get("use_huggingface"), False),
            force_overwrite_by_default=_as_bool(
                data.get("force_overwrite_by_default"), False
            ),
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


_TRUE_WORDS = frozenset({"1", "true", "yes", "on"})
_FALSE_WORDS = frozenset({"0", "false", "no", "off", ""})


def _as_bool(value: Any, fallback: bool) -> bool:
    """Read a boolean setting, accepting only values we can actually interpret.

    ``bool(value)`` is wrong for this job: it turns the string ``"false"`` into
    ``True``. Hand-edited config is a supported case, so the accepted spellings
    are listed explicitly and anything else returns ``fallback`` rather than
    guessing — an unrecognised value must not silently enable a setting.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        # 0 and 1 only. 2 is not a truthy boolean, it is a value we do not
        # understand, and defaulting is safer than coercing.
        return bool(value) if value in (0, 1) else fallback
    if isinstance(value, str):
        word = value.strip().lower()
        if word in _TRUE_WORDS:
            return True
        if word in _FALSE_WORDS:
            return False
        return fallback
    return fallback


def _as_str_list(value: Any) -> List[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if str(item).strip()]


def load_config(
    path: Optional[Path] = None,
    warnings: Optional[List[str]] = None,
) -> AppConfig:
    """Load the config file, falling back to defaults when it is missing or broken.

    ``warnings``, when supplied, collects a note for any file that existed but
    could not be used. Falling back to defaults is right — a broken settings
    file must not stop the app starting — but doing it *silently* is not: the
    user's saved paths are gone, and the only symptom is "lmstudio-caplift.exe
    was not found", which points nowhere near the cause. Callers pass a list
    and surface it.
    """
    target = path or config_path()
    if not target.exists():
        return AppConfig()
    try:
        raw = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        _note(
            warnings,
            f"{target} could not be read ({exc}). Default settings are in use; "
            "saving will overwrite it.",
        )
        return AppConfig()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        _note(
            warnings,
            f"{target} is not valid JSON ({exc}). Default settings are in use; "
            "saving will overwrite it.",
        )
        return AppConfig()
    if not isinstance(data, dict):
        _note(
            warnings,
            f"{target} does not contain a settings object. Default settings are "
            "in use; saving will overwrite it.",
        )
        return AppConfig()
    return AppConfig.from_dict(data)


def _note(warnings: Optional[List[str]], message: str) -> None:
    if warnings is not None:
        warnings.append(message)


def save_config(config: AppConfig, path: Optional[Path] = None) -> Optional[str]:
    """Write the config file. Returns an error string on failure, otherwise None.

    Written to a temporary file and moved into place with ``os.replace``, which
    is atomic on the same volume. A direct write can be interrupted part-way —
    the window closing mid-save is enough — leaving truncated JSON that
    ``load_config`` then reads as "no settings at all".

    The temporary file gets a unique name via ``mkstemp`` rather than a fixed
    ``.<name>.tmp``. Two saves racing on one path would share that file: one
    could replace it while the other is still writing, or clean it up after the
    other had closed it, so each save now owns its own file.

    Unique names alone are not enough on Windows, though. Two ``os.replace``
    calls onto the *same* destination can collide, and the loser fails with
    ``WinError 5 (Access is denied)`` rather than simply losing the race. The
    lock serialises the rename, which covers the real case — one UI process
    saving from a button and again on close. Writers in separate processes are
    not serialised and are out of scope for a single-window app.
    """
    target = path or config_path()
    temp_name: Optional[str] = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(config.to_dict(), indent=2) + "\n"
        # Same directory as the target: os.replace is only atomic within a
        # volume, and %TEMP% is frequently on a different one.
        fd, temp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        with _SAVE_LOCK:
            os.replace(temp_name, target)
        temp_name = None
    except OSError as exc:
        return f"Could not save {target}: {exc}"
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
    return None
