"""Tests for CLI runner error handling (S1: list_registry error paths).

These tests stub ``CliRunner.run`` with canned :class:`CliResult` values so
they exercise only ``list_registry`` branch logic — no subprocess, no
filesystem artifacts, no real CLI. The timeout test fakes the subprocess
layer the same way.

Run with:
    python -m unittest discover -s tests -t .
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from caplift_ui import cli_runner as cli_runner_module
from caplift_ui.cli_runner import CliCommandError, CliError, CliResult, CliRunner, CliTimeoutError
from caplift_ui.tasks import describe_exception

FAKE_CLI = Path("fake-lmstudio-cli.exe")

EMPTY_REGISTRY = json.dumps({"availableModels": [], "wrappedModels": []})


def make_result(returncode: int, stdout: str = "", stderr: str = "") -> CliResult:
    return CliResult(
        args=[str(FAKE_CLI), "list", "--json", "--all"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def stub_runner(result: CliResult) -> CliRunner:
    """A runner whose transport is a canned CliResult — no subprocess."""
    runner = CliRunner(cli_path=FAKE_CLI)
    runner.run = lambda args, timeout=None: result  # type: ignore[method-assign]
    return runner


class ListRegistryErrorTests(unittest.TestCase):
    """S1: list_registry must surface CLI failures instead of parsing them."""

    def test_s1_1_nonzero_exit_with_valid_json_raises(self) -> None:
        # Regression: the CLI failed but still printed parseable JSON.
        # list_registry must raise CliCommandError, not return a RegistryView.
        runner = stub_runner(make_result(1, stdout=EMPTY_REGISTRY, stderr="boom"))
        with self.assertRaises(CliCommandError) as ctx:
            runner.list_registry()
        self.assertEqual(ctx.exception.result.returncode, 1)
        self.assertEqual(ctx.exception.result.stderr, "boom")

    def test_s1_2_nonzero_exit_with_empty_stdout_raises(self) -> None:
        # Behavior-preserving: failure with no stdout still raises, with the
        # full CliResult attached.
        runner = stub_runner(make_result(1, stderr="boom"))
        with self.assertRaises(CliCommandError) as ctx:
            runner.list_registry()
        self.assertEqual(ctx.exception.result.returncode, 1)
        self.assertEqual(ctx.exception.result.stderr, "boom")

    def test_s1_3_zero_exit_with_blank_stdout_raises(self) -> None:
        # Exit 0 but nothing printed: the real CLI emits valid empty JSON for
        # an empty registry (verified against 0.2.0), so blank stdout is a
        # defect, not an empty registry. Must be plain CliError — NOT
        # CliCommandError — because describe_exception routes CliCommandError
        # through describe_cli_error, which would discard this message and
        # report "exited with an error" for a zero-exit run.
        runner = stub_runner(make_result(0, stdout="   \n  "))
        with self.assertRaises(CliError) as ctx:
            runner.list_registry()
        self.assertNotIsInstance(ctx.exception, CliCommandError)
        self.assertEqual(
            describe_exception(ctx.exception),
            "lmstudio-caplift exited successfully but printed no output; "
            "expected registry JSON.",
        )

    def test_s1_4_zero_exit_with_valid_empty_json_returns_empty_registry(self) -> None:
        # A real empty registry is valid empty JSON and must keep working.
        runner = stub_runner(make_result(0, stdout=EMPTY_REGISTRY))
        registry = runner.list_registry()
        self.assertEqual(registry.available_count, 0)
        self.assertEqual(registry.wrapped_count, 0)

    def test_s1_5_zero_exit_with_garbage_stdout_raises_fixed_message(self) -> None:
        # Exit 0 with unparseable output: fixed, leak-safe message with no
        # raw stdout echoed. (Expected message change, not a leak fix — the
        # baseline message was already clean of raw output.)
        runner = stub_runner(make_result(0, stdout="not json at all"))
        with self.assertRaises(CliError) as ctx:
            runner.list_registry()
        self.assertNotIsInstance(ctx.exception, CliCommandError)
        message = str(ctx.exception)
        self.assertEqual(
            message,
            "lmstudio-caplift exited successfully but its output was not "
            "understandable registry JSON.",
        )
        self.assertNotIn("not json at all", message)


class RunTimeoutTests(unittest.TestCase):
    """Timeout keeps its own distinct error, separate from command failure."""

    def test_s1_6_timeout_expired_becomes_cli_timeout_error(self) -> None:
        # Behavior-preserving: subprocess.TimeoutExpired is translated into
        # CliTimeoutError (not CliCommandError), with the configured limit
        # named in the message.
        runner = CliRunner(cli_path=FAKE_CLI, timeout_seconds=10)
        with unittest.mock.patch.object(
            cli_runner_module.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="x", timeout=10, output=b""),
        ):
            with self.assertRaises(CliTimeoutError) as ctx:
                runner.run(["list"])
        self.assertIn("did not finish within 10s", str(ctx.exception))
        self.assertNotIsInstance(ctx.exception, CliCommandError)


if __name__ == "__main__":
    unittest.main()
