"""Tests for base-template discovery and checking.

Unlike the dialog bug, this logic is pure filesystem work, so it is fully
testable headlessly against a temporary directory.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from caplift_ui.config import (
    default_hub_models_dirs,
    hub_models_dir_candidates,
    resolve_hub_models_dir,
)
from caplift_ui.templates import (
    BaseTemplate,
    check_template,
    find_installed_templates,
    looks_like_model_id,
)


def install_model(hub: Path, model_id: str, with_manifest: bool = True, with_yaml: bool = True) -> Path:
    """Create a hub-model directory holding the requested files."""
    path = hub.joinpath(*model_id.split("/"))
    path.mkdir(parents=True, exist_ok=True)
    if with_manifest:
        (path / "manifest.json").write_text(json.dumps({"owner": model_id.split("/")[0]}), encoding="utf-8")
    if with_yaml:
        (path / "model.yaml").write_text("model: placeholder\n", encoding="utf-8")
    return path


class DiscoveryTests(unittest.TestCase):
    def test_finds_models_with_both_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hub = Path(tmp)
            install_model(hub, "qwen/qwen3.8-27b")
            install_model(hub, "meta/muse-glimmer")
            found = find_installed_templates(hub)
            self.assertEqual([t.model_id for t in found], ["meta/muse-glimmer", "qwen/qwen3.8-27b"])

    def test_official_models_come_before_wrappers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hub = Path(tmp)
            install_model(hub, "local/my-wrapper")
            install_model(hub, "qwen/qwen3.8-27b")
            found = find_installed_templates(hub)
            self.assertEqual([t.model_id for t in found], ["qwen/qwen3.8-27b", "local/my-wrapper"])
            self.assertTrue(found[1].is_wrapper)
            self.assertFalse(found[0].is_wrapper)

    def test_skips_incomplete_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hub = Path(tmp)
            install_model(hub, "qwen/has-everything")
            install_model(hub, "qwen/no-yaml", with_yaml=False)
            install_model(hub, "qwen/no-manifest", with_manifest=False)
            found = find_installed_templates(hub)
            self.assertEqual([t.model_id for t in found], ["qwen/has-everything"])

    def test_ignores_stray_files_and_loose_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hub = Path(tmp)
            (hub / ".lmstudio-caplift.json").write_text("{}", encoding="utf-8")
            (hub / "stray-file.txt").write_text("x", encoding="utf-8")
            (hub / "owner-without-models").mkdir()
            (hub / ".hidden").mkdir()
            self.assertEqual(find_installed_templates(hub), [])

    def test_missing_hub_dir_yields_nothing(self) -> None:
        self.assertEqual(find_installed_templates(None), [])
        self.assertEqual(find_installed_templates(Path(r"Z:\does\not\exist")), [])

    def test_template_is_immutable(self) -> None:
        template = BaseTemplate("qwen/qwen3.8-27b", Path("x"))
        with self.assertRaises(Exception):
            template.model_id = "other"  # type: ignore[misc]


class CheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.hub = Path(self._tmp.name)
        install_model(self.hub, "qwen/qwen3.8-27b")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_installed_template_is_found(self) -> None:
        check = check_template(self.hub, "qwen/qwen3.8-27b")
        self.assertTrue(check.checked)
        self.assertTrue(check.found)
        self.assertEqual(check.path, self.hub / "qwen" / "qwen3.8-27b")

    def test_missing_template_reports_the_path_checked(self) -> None:
        check = check_template(self.hub, "qwen/qwen3-30b-a3b")
        self.assertTrue(check.checked)
        self.assertFalse(check.found)
        self.assertIn("qwen3-30b-a3b", check.reason)
        self.assertIn("Not installed", check.reason)

    def test_incomplete_template_is_rejected(self) -> None:
        install_model(self.hub, "qwen/half-installed", with_yaml=False)
        check = check_template(self.hub, "qwen/half-installed")
        self.assertFalse(check.found)
        self.assertIn("model.yaml", check.reason)

    def test_unknown_hub_dir_is_not_a_denial(self) -> None:
        # checked=False means "could not verify" — callers must not block on it.
        check = check_template(None, "qwen/qwen3.8-27b")
        self.assertFalse(check.checked)
        self.assertFalse(check.found)
        self.assertEqual(check.reason, "")

    def test_shape_validation(self) -> None:
        self.assertTrue(check_template(self.hub, "qwen/qwen3.8-27b").checked)
        for bad in ("qwen3.8-27b", "a/b/c", ""):
            check = check_template(self.hub, bad)
            self.assertFalse(check.found, bad)

    def test_empty_value_is_not_treated_as_installed(self) -> None:
        check = check_template(self.hub, "   ")
        self.assertFalse(check.found)

    def test_model_id_shape_helper(self) -> None:
        self.assertTrue(looks_like_model_id("qwen/qwen3.8-27b"))
        self.assertFalse(looks_like_model_id("qwen3.8-27b"))
        self.assertFalse(looks_like_model_id("a/b/c"))
        self.assertFalse(looks_like_model_id("a/"))
        self.assertFalse(looks_like_model_id("/b"))
        self.assertFalse(looks_like_model_id(""))


class HubDirResolutionTests(unittest.TestCase):
    def test_configured_dir_wins_outright(self) -> None:
        candidates = hub_models_dir_candidates(r"D:\LM Studio\hub\models")
        self.assertEqual(len(candidates), 1)
        self.assertEqual(str(candidates[0]), r"D:\LM Studio\hub\models")

    def test_defaults_cover_both_known_layouts(self) -> None:
        names = [str(path).replace("\\", "/") for path in default_hub_models_dirs()]
        self.assertTrue(names[0].endswith(".lmstudio/hub/models"))
        self.assertTrue(names[1].endswith(".cache/lm-studio/hub/models"))

    def test_resolution_returns_only_real_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(resolve_hub_models_dir(tmp), Path(tmp))
        self.assertIsNone(resolve_hub_models_dir(r"Z:\definitely\missing"))

    def test_a_configured_missing_dir_is_not_silently_replaced(self) -> None:
        # Passing --hub-models-dir means the CLI uses exactly that, so the UI
        # must not fall back to a default that the CLI will never look at.
        self.assertIsNone(resolve_hub_models_dir(r"Z:\definitely\missing"))


if __name__ == "__main__":
    unittest.main()
