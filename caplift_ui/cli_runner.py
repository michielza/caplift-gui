"""Subprocess wrapper around ``lmstudio-caplift.exe``."""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

from .config import AppConfig, DEFAULT_TIMEOUT_SECONDS, find_cli
from .models import RegistryView
from .parser import DryRunPreview, ParseError, parse_dry_run, parse_registry_json


class CliError(RuntimeError):
    """Base class for problems talking to lmstudio-caplift."""


class CliNotFoundError(CliError):
    """The caplift executable could not be located."""


class CliTimeoutError(CliError):
    """The command did not finish within the configured timeout."""


class CliCommandError(CliError):
    """The command ran but returned a non-zero exit code."""

    def __init__(self, message: str, result: "CliResult") -> None:
        super().__init__(message)
        self.result = result


@dataclass
class CliResult:
    """Outcome of one CLI invocation."""

    args: Sequence[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def combined_output(self) -> str:
        parts = [part for part in (self.stdout, self.stderr) if part and part.strip()]
        return "\n".join(parts).strip()

    @property
    def command_line(self) -> str:
        return " ".join(_quote_for_display(part) for part in self.args)


def _quote_for_display(value: str) -> str:
    return f'"{value}"' if any(char in value for char in ' \t"') else value


def _no_window_kwargs() -> dict:
    """Keep subprocesses from flashing a console window in the frozen UI."""
    if os.name != "nt":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}


@dataclass
class CliRunner:
    """Runs caplift commands and parses their output.

    A runner is cheap; the UI builds a fresh one per action so that settings
    changes (paths, timeout) take effect immediately.
    """

    cli_path: Path
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    hub_models_dir: Optional[str] = None
    lms_path: Optional[str] = None

    # ---- construction --------------------------------------------------

    @classmethod
    def from_config(cls, config: AppConfig) -> "CliRunner":
        """Build a runner from saved settings, or raise if the CLI is missing."""
        resolved = find_cli(config.cli_path)
        if resolved is None:
            raise CliNotFoundError(
                "lmstudio-caplift.exe was not found. Place it next to this UI "
                "executable, or set its location in Settings."
            )
        return cls(
            cli_path=resolved,
            timeout_seconds=_sane_timeout(config.timeout_seconds),
            hub_models_dir=config.hub_models_dir,
            lms_path=config.lms_path,
        )

    # ---- low level -----------------------------------------------------

    def run(self, args: Sequence[str], timeout: Optional[int] = None) -> CliResult:
        """Run one subcommand and capture its output."""
        command: List[str] = [str(self.cli_path), *args]
        limit = _sane_timeout(timeout if timeout is not None else self.timeout_seconds)
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=limit,
                cwd=str(self.cli_path.parent),
                **_no_window_kwargs(),
            )
        except subprocess.TimeoutExpired as exc:
            raise CliTimeoutError(
                f"lmstudio-caplift did not finish within {limit}s. "
                "Increase the timeout in Settings if this is expected."
            ) from exc
        except OSError as exc:
            raise CliError(f"Could not run {self.cli_path}: {exc}") from exc

        return CliResult(
            args=command,
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            duration_seconds=time.monotonic() - started,
        )

    def run_checked(self, args: Sequence[str], timeout: Optional[int] = None) -> CliResult:
        """Run a subcommand and raise :class:`CliCommandError` on failure."""
        result = self.run(args, timeout=timeout)
        if not result.ok:
            raise CliCommandError(result.combined_output or "Command failed", result)
        return result

    # ---- shared option plumbing ---------------------------------------

    def _global_options(self) -> List[str]:
        options: List[str] = []
        if self.hub_models_dir:
            options += ["--hub-models-dir", self.hub_models_dir]
        return options

    # ---- commands ------------------------------------------------------

    def version(self) -> str:
        try:
            result = self.run(["--version"], timeout=30)
        except CliError as exc:
            raise exc
        return result.combined_output or "unknown"

    def list_registry(
        self,
        include_available: bool = True,
        use_huggingface: bool = False,
    ) -> RegistryView:
        """Run ``list --json`` and parse the registry.

        ``include_available`` adds ``--all`` so installed-but-unwrapped models
        are included. That path calls ``lms`` and therefore needs LM Studio to
        be reachable; the caller decides how to present that failure.
        """
        args: List[str] = ["list", "--json", *self._global_options()]
        if include_available:
            args.append("--all")
            if use_huggingface:
                args.append("--huggingface")
            if self.lms_path:
                args += ["--lms", self.lms_path]

        result = self.run(args)
        text = result.stdout.strip()

        if not result.ok:
            # Non-zero exit: keep the full CliResult for the log console.
            raise CliCommandError(result.combined_output or "list failed", result)

        if not text:
            # Exit 0 but nothing printed. The real CLI emits valid empty JSON
            # for an empty registry (verified against 0.2.0), so blank stdout
            # is a defect, not an empty registry. Plain CliError, NOT
            # CliCommandError: describe_exception routes CliCommandError
            # through describe_cli_error, which would discard this message
            # and report "exited with an error" for a zero-exit run.
            raise CliError(
                "lmstudio-caplift exited successfully but printed no output; "
                "expected registry JSON.")

        try:
            return parse_registry_json(text)
        except ParseError:
            # Fixed UI text, no interpolation. JSONDecodeError retains the
            # input in .doc, so echoing the exception risks leaking registry
            # contents.
            raise CliError(
                "lmstudio-caplift exited successfully but its output was not "
                "understandable registry JSON.")

    def list_tracked(self) -> RegistryView:
        """Run ``list --json`` without ``--all`` (no LM Studio required)."""
        return self.list_registry(include_available=False)

    def wrap(
        self,
        model_key: str,
        wrapper_model_id: Optional[str] = None,
        base_model_id: Optional[str] = None,
        hf_repo: Optional[str] = None,
        dry_run: bool = False,
        force: bool = False,
    ) -> CliResult:
        """Run ``wrap`` for one model."""
        args: List[str] = ["wrap", model_key, *self._global_options()]
        if wrapper_model_id:
            args += ["--wrapper-model-id", wrapper_model_id]
        if base_model_id:
            args += ["--base-model-id", base_model_id]
        if hf_repo:
            args += ["--hf-repo", hf_repo]
        if dry_run:
            args.append("--dry-run")
        if force:
            args.append("--force")
        return self.run(args)

    def preview_wrap(
        self,
        model_key: str,
        wrapper_model_id: Optional[str] = None,
        base_model_id: Optional[str] = None,
        hf_repo: Optional[str] = None,
    ) -> DryRunPreview:
        """Run ``wrap --dry-run`` and parse the generated files."""
        result = self.wrap(
            model_key=model_key,
            wrapper_model_id=wrapper_model_id,
            base_model_id=base_model_id,
            hf_repo=hf_repo,
            dry_run=True,
        )
        if not result.ok:
            raise CliCommandError(result.combined_output or "dry run failed", result)
        preview = parse_dry_run(result.stdout)
        if not preview.files:
            # Nothing parsed: surface the raw text rather than an empty dialog.
            preview = DryRunPreview(raw_text=result.stdout, header=preview.header)
        return preview


def _sane_timeout(value: Optional[int]) -> int:
    try:
        parsed = int(value) if value is not None else DEFAULT_TIMEOUT_SECONDS
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    return max(5, min(parsed, 3600))
