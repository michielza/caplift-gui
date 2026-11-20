"""Tests for output parsing and config handling.

Run with:
    python -m unittest discover -s tests -t .
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from caplift_ui.config import AppConfig, config_path, find_cli, load_config, save_config
from caplift_ui.models import derive_wrapper_id
from caplift_ui.parser import (
    ParseError,
    describe_cli_error,
    parse_dry_run,
    parse_registry_json,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class ParseRegistryTests(unittest.TestCase):
    def test_reads_tracked_wrapper_from_real_output(self) -> None:
        payload = (FIXTURES / "list_tracked.json").read_text(encoding="utf-8")
        registry = parse_registry_json(payload)

        self.assertEqual(registry.wrapped_count, 1)
        self.assertEqual(registry.available_count, 0)

        wrapped = registry.wrapped[0]
        self.assertEqual(wrapped.wrapper_model_id, "local/muse-glimmer-30b-abliterated-gguf")
        self.assertEqual(wrapped.base_model_id, "meta/muse-glimmer")
        self.assertEqual(
            wrapped.model_key,
            "The-freezer/Muse-Glimmer-30B-Abliterated-GGUF/Muse-Glimmer-30B-Abliterated-Q4_K_M.gguf",
        )
        self.assertEqual(wrapped.created_at_unix_seconds, 1795206747)
        self.assertNotEqual(wrapped.created_display, "—")
        self.assertTrue(str(wrapped.target_path).replace("\\", "/").endswith("local/muse-glimmer-30b-abliterated-gguf"))

    def test_reads_available_models_and_null_base_template(self) -> None:
        payload = json.dumps(
            {
                "availableModels": [
                    {
                        "modelKey": "unsloth/Qwen3.5-35B-A3B-GGUF/Qwen3.5-35B-A3B-UD-Q4_K_L.gguf",
                        "wrapperModelId": "local/qwen3.5-35b-a3b",
                        "baseModelId": "qwen/qwen3.5-35b-a3b",
                    },
                    {
                        "modelKey": "some/Unknown-Model-GGUF/Unknown-Q4.gguf",
                        "wrapperModelId": "local/unknown-model",
                        "baseModelId": None,
                    },
                ],
                "wrappedModels": [],
            }
        )
        registry = parse_registry_json(payload)

        self.assertEqual(registry.available_count, 2)
        first, second = registry.available
        self.assertEqual(first.base_model_id, "qwen/qwen3.5-35b-a3b")
        self.assertTrue(first.has_base_template)
        self.assertEqual(first.suggested_wrapper_id, "local/qwen3.5-35b-a3b")
        self.assertIsNone(second.base_model_id)
        self.assertFalse(second.has_base_template)

    def test_treats_na_string_as_missing_base_template(self) -> None:
        payload = json.dumps(
            {"availableModels": [{"modelKey": "a/b", "baseModelId": "N/A"}], "wrappedModels": []}
        )
        registry = parse_registry_json(payload)
        self.assertIsNone(registry.available[0].base_model_id)

    def test_tolerates_alternate_keys_and_dict_shaped_maps(self) -> None:
        payload = json.dumps(
            {
                "available": {
                    "a/b/c.gguf": {
                        "key": "a/b/c.gguf",
                        "wrapper": "local/c",
                        "template": "owner/name",
                    }
                },
                "wrapped": [{"wrapper": "local/c", "model": "a/b/c.gguf", "baseTemplate": "owner/name"}],
            }
        )
        registry = parse_registry_json(payload)
        self.assertEqual(registry.available_count, 1)
        self.assertEqual(registry.wrapped_count, 1)
        self.assertEqual(registry.available[0].base_model_id, "owner/name")
        self.assertEqual(registry.wrapped[0].base_model_id, "owner/name")

    def test_empty_output_yields_empty_registry(self) -> None:
        registry = parse_registry_json("")
        self.assertEqual(registry.available_count, 0)
        self.assertEqual(registry.wrapped_count, 0)

    def test_garbage_output_raises_parse_error(self) -> None:
        with self.assertRaises(ParseError):
            parse_registry_json("Error: something went wrong")


class DryRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.preview = parse_dry_run((FIXTURES / "dry_run.txt").read_text(encoding="utf-8"))

    def test_parses_header(self) -> None:
        self.assertEqual(self.preview.wrapper_model_id, "local/muse-glimmer-30b-abliterated-gguf")
        self.assertEqual(self.preview.base_model_id, "meta/muse-glimmer")
        self.assertEqual(
            self.preview.model_key,
            "The-freezer/Muse-Glimmer-30B-Abliterated-GGUF/Muse-Glimmer-30B-Abliterated-Q4_K_M.gguf",
        )
        self.assertTrue(self.preview.target_dir.endswith("muse-glimmer-30b-abliterated-gguf"))
        self.assertTrue(self.preview.registry_path.endswith(".lmstudio-caplift.json"))

    def test_parses_generated_files(self) -> None:
        self.assertEqual(self.preview.file_names, ("manifest.json", "model.yaml"))
        contents = dict(self.preview.files)
        manifest = next(body for path, body in contents.items() if path.endswith("manifest.json"))
        model_yaml = next(body for path, body in contents.items() if path.endswith("model.yaml"))

        self.assertIn('"owner": "local"', manifest)
        # model must differ from base.key or LM Studio hides the wrapper
        self.assertIn("model: local/muse-glimmer-30b-abliterated-gguf", model_yaml)
        self.assertIn("base:", model_yaml)

    def test_handles_output_without_file_sections(self) -> None:
        preview = parse_dry_run("some unexpected text")
        self.assertEqual(preview.files, ())
        self.assertEqual(preview.raw_text, "some unexpected text")


class ErrorMessageTests(unittest.TestCase):
    def test_missing_base_template_is_explained(self) -> None:
        message = describe_cli_error(
            "Error: no suitable static base template found for some/model; pass --base-model-id"
        )
        self.assertIn("some/model", message)
        self.assertIn("--base-model-id".replace("--", ""), message)

    def test_lm_studio_down_is_explained(self) -> None:
        message = describe_cli_error(
            "Error: No running LM Studio or Bionic app, and no valid installation was found."
        )
        self.assertIn("LM Studio is not running", message)

    def test_unknown_error_falls_back_to_first_error_line(self) -> None:
        message = describe_cli_error("warning: something\nError: the real problem\nmore noise")
        self.assertEqual(message, "Error: the real problem")


class WrapperIdTests(unittest.TestCase):
    def test_three_part_key_uses_repo_segment(self) -> None:
        self.assertEqual(
            derive_wrapper_id(
                "The-freezer/Muse-Glimmer-30B-Abliterated-GGUF/Muse-Glimmer-30B-Abliterated-Q4_K_M.gguf"
            ),
            "local/muse-glimmer-30b-abliterated-gguf",
        )

    def test_two_part_key_uses_name_segment(self) -> None:
        self.assertEqual(derive_wrapper_id("unsloth/qwen3.5-35b-a3b"), "local/qwen3-5-35b-a3b")

    def test_dots_become_dashes_to_match_the_cli(self) -> None:
        self.assertEqual(derive_wrapper_id("granite-4.2-30b"), "local/granite-4-2-30b")

    def test_plain_name(self) -> None:
        self.assertEqual(derive_wrapper_id("Qwen3.5-35B-A3B-UD-Q4_K_L.gguf"), "local/qwen3-5-35b-a3b-ud-q4_k_l")


class RealListingTests(unittest.TestCase):
    """Guards the real CLI schema.

    Available models use ``defaultWrapperModelId`` / ``selectedBaseModelId``;
    wrapped models use ``wrapperModelId`` / ``baseModelId``. Mixing these up
    silently showed "N/A" for models that do have a base template, so the real
    capture is pinned here.
    """

    def setUp(self) -> None:
        payload = (FIXTURES / "list_all.json").read_text(encoding="utf-8")
        self.registry = parse_registry_json(payload)

    def _model(self, needle: str):
        return next(m for m in self.registry.available if needle in m.model_key)

    def test_counts(self) -> None:
        self.assertEqual(self.registry.available_count, 8)
        self.assertEqual(self.registry.wrapped_count, 1)

    def test_uses_cli_default_wrapper_id_not_a_guess(self) -> None:
        granite = self._model("granite-4.2-30b")
        # The CLI rewrites dots to dashes; a naive derivation would keep "4.2".
        self.assertEqual(granite.suggested_wrapper_id, "local/granite-4-2-30b")
        self.assertEqual(granite.display_name, "Granite 4.2 30B")
        self.assertEqual(granite.publisher, "lmstudio-community")
        self.assertEqual(granite.params_string, "30B")

    def test_reads_selected_base_model_id(self) -> None:
        nemotron = self._model("nemotron")
        self.assertEqual(nemotron.base_model_id, "nvidia/nemotron-3-nano-omni")
        self.assertTrue(nemotron.has_base_template)

    def test_null_selected_base_model_id_means_no_match(self) -> None:
        granite = self._model("granite-4.2-30b")
        self.assertIsNone(granite.base_model_id)
        self.assertFalse(granite.has_base_template)

    def test_wrapped_entry_from_the_real_registry(self) -> None:
        wrapped = self.registry.wrapped[0]
        self.assertEqual(wrapped.wrapper_model_id, "local/muse-glimmer-30b-abliterated-gguf")
        self.assertEqual(wrapped.base_model_id, "meta/muse-glimmer")


class ConfigTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "caplift_ui_config.json"
            config = AppConfig(
                cli_path=r"C:\tools\lmstudio-caplift.exe",
                hub_models_dir=r"C:\Users\example\.lmstudio\hub\models",
                timeout_seconds=120,
                use_huggingface=True,
            )
            config.window.width = 1400
            config.window.height = 900
            self.assertIsNone(save_config(config, path))

            loaded = load_config(path)
            self.assertEqual(loaded.cli_path, config.cli_path)
            self.assertEqual(loaded.hub_models_dir, config.hub_models_dir)
            self.assertEqual(loaded.timeout_seconds, 120)
            self.assertTrue(loaded.use_huggingface)
            self.assertEqual(loaded.window.width, 1400)
            self.assertEqual(loaded.window.height, 900)

    def test_missing_file_gives_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            loaded = load_config(Path(tmp) / "absent.json")
            self.assertIsNone(loaded.cli_path)
            self.assertEqual(loaded.timeout_seconds, 300)

    def test_corrupt_file_gives_defaults_instead_of_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "caplift_ui_config.json"
            path.write_text("{ this is not json", encoding="utf-8")
            loaded = load_config(path)
            self.assertIsNone(loaded.cli_path)

    def test_remember_moves_value_to_front_and_dedupes(self) -> None:
        config = AppConfig()
        config.remember("recent_base_templates", "owner/one")
        config.remember("recent_base_templates", "owner/two")
        config.remember("recent_base_templates", "owner/one")
        self.assertEqual(config.recent_base_templates, ["owner/one", "owner/two"])

    def test_config_path_sits_next_to_the_app(self) -> None:
        self.assertEqual(config_path().name, "caplift_ui_config.json")


class CliDiscoveryTests(unittest.TestCase):
    def test_missing_override_falls_back_to_auto_detection(self) -> None:
        # An override that does not exist must not be returned as-is.
        self.assertNotEqual(
            find_cli(r"C:\definitely\not\here\lmstudio-caplift.exe"),
            Path(r"C:\definitely\not\here\lmstudio-caplift.exe"),
        )


if __name__ == "__main__":
    unittest.main()
