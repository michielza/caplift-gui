"""Tests for output parsing and config handling.

Run with:
    python -m unittest discover -s tests -t .
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from caplift_ui.config import (
    DEFAULT_TIMEOUT_SECONDS,
    MAX_TIMEOUT_SECONDS,
    MIN_TIMEOUT_SECONDS,
    AppConfig,
    config_path,
    find_cli,
    load_config,
    sane_timeout,
    save_config,
)
from caplift_ui.models import AvailableModel, derive_hf_repo, derive_wrapper_id
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

    def test_auto_selected_template_that_is_not_installed_is_explained(self) -> None:
        # Real output: the field was blank, so the CLI chose a template itself
        # and discovered it is not installed.
        message = describe_cli_error(
            "Error: base template qwen/qwen3-30b-a3b is not installed at "
            r"C:\Users\example\.lmstudio\hub\models\qwen\qwen3-30b-a3b"
        )
        self.assertIn("qwen/qwen3-30b-a3b", message)
        self.assertIn("not installed", message)
        self.assertIn("Base template field", message)
        # Must be distinguishable from "no template matched at all".
        self.assertNotIn("No static base template matched", message)

    def test_declined_match_is_still_explained_separately(self) -> None:
        message = describe_cli_error(
            "Error: no suitable static base template found for some/model; pass --base-model-id"
        )
        self.assertIn("No static base template matched", message)
        self.assertNotIn("left empty", message)

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


class HfRepoTests(unittest.TestCase):
    """Deriving owner/repo from an installed file path.

    Conservative by design: a wrong repository writes false provenance into the
    generated files, so anything that is not exactly owner/repo/file.gguf must
    return None rather than a guess.
    """

    def test_real_lms_path_yields_owner_and_repo(self) -> None:
        self.assertEqual(
            derive_hf_repo("lmstudio-community/granite-4.2-30b-GGUF/granite-4.2-30b-Q4_K_M.gguf"),
            "lmstudio-community/granite-4.2-30b-GGUF",
        )

    def test_three_part_path_with_uppercase_and_hyphens(self) -> None:
        self.assertEqual(
            derive_hf_repo(
                "The-freezer/Muse-Glimmer-30B-Abliterated-GGUF/Muse-Glimmer-30B-Abliterated-Q4_K_M.gguf"
            ),
            "The-freezer/Muse-Glimmer-30B-Abliterated-GGUF",
        )

    def test_backslashes_are_accepted(self) -> None:
        self.assertEqual(
            derive_hf_repo("unsloth\\Qwen3-GGUF\\Qwen3-Q4.gguf"),
            "unsloth/Qwen3-GGUF",
        )

    def test_windows_absolute_path_is_rejected(self) -> None:
        # Would otherwise yield the nonsense owner "D:".
        self.assertIsNone(derive_hf_repo("D:\\models\\llama\\llama-3.gguf"))
        self.assertIsNone(derive_hf_repo("C:/Users/example/models/llama-3.gguf"))

    def test_unix_absolute_path_is_rejected(self) -> None:
        self.assertIsNone(derive_hf_repo("/home/user/models/llama-3.gguf"))

    def test_wrong_segment_count_is_rejected(self) -> None:
        # A subfolder inside a repo would make owner/repo ambiguous.
        self.assertIsNone(derive_hf_repo("owner/repo/subdir/model.gguf"))
        self.assertIsNone(derive_hf_repo("owner/model.gguf"))
        self.assertIsNone(derive_hf_repo("model.gguf"))

    def test_non_gguf_filename_is_rejected(self) -> None:
        self.assertIsNone(derive_hf_repo("owner/repo/model.safetensors"))

    def test_missing_path_is_rejected(self) -> None:
        self.assertIsNone(derive_hf_repo(None))
        self.assertIsNone(derive_hf_repo(""))

    def test_available_model_prefers_the_reported_repo(self) -> None:
        # A CLI-reported value beats the derived guess.
        model = AvailableModel(
            model_key="a/b.gguf", hf_repo="explicit/repo", path="owner/derived/file.gguf"
        )
        self.assertEqual(model.suggested_hf_repo, "explicit/repo")

    def test_available_model_falls_back_to_the_path(self) -> None:
        model = AvailableModel(model_key="a", path="owner/derived/file.gguf")
        self.assertEqual(model.suggested_hf_repo, "owner/derived")

    def test_available_model_without_path_has_no_suggestion(self) -> None:
        self.assertIsNone(AvailableModel(model_key="a").suggested_hf_repo)

    def test_real_fixture_row_yields_a_repo(self) -> None:
        payload = (FIXTURES / "list_all.json").read_text(encoding="utf-8")
        registry = parse_registry_json(payload)
        granite = next(m for m in registry.available if m.model_key == "granite-4.2-30b")
        self.assertEqual(granite.suggested_hf_repo, "lmstudio-community/granite-4.2-30b-GGUF")
        # Every row in the real capture follows the same shape, so all should
        # produce something rather than silently leaving the field blank.
        self.assertTrue(all(m.suggested_hf_repo for m in registry.available))


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


class ConfigPersistenceTests(unittest.TestCase):
    """Saving is atomic and a broken file says so."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.path = self.dir / "caplift_ui_config.json"

    def test_save_leaves_no_temporary_file_behind(self) -> None:
        self.assertIsNone(save_config(AppConfig(timeout_seconds=45), self.path))
        self.assertEqual([p.name for p in self.dir.iterdir()], [self.path.name])

    def test_no_temp_file_survives_a_failed_save(self) -> None:
        # A directory where the file should go: the replace cannot succeed, and
        # the half-written temp file must not be left lying next to it.
        self.path.mkdir()
        self.assertIsNotNone(save_config(AppConfig(), self.path))
        self.assertEqual(list(self.dir.glob("*.tmp")), [])
        self.assertEqual(list(self.dir.glob(".*.tmp")), [])

    def test_existing_file_is_replaced_not_truncated(self) -> None:
        save_config(AppConfig(timeout_seconds=60), self.path)
        save_config(AppConfig(timeout_seconds=90), self.path)
        self.assertEqual(load_config(self.path).timeout_seconds, 90)

    def test_corrupt_file_is_reported(self) -> None:
        # Silent fallback is the bug: the saved paths vanish and the only
        # symptom is a missing executable.
        self.path.write_text("{ this is not json", encoding="utf-8")
        warnings: list = []
        loaded = load_config(self.path, warnings=warnings)
        self.assertIsNone(loaded.cli_path)
        self.assertEqual(len(warnings), 1)
        self.assertIn("not valid JSON", warnings[0])

    def test_absent_file_is_not_a_warning(self) -> None:
        # First run writes no config, and that is not a problem to report.
        warnings: list = []
        load_config(self.dir / "absent.json", warnings=warnings)
        self.assertEqual(warnings, [])

    def test_unreadable_file_is_reported(self) -> None:
        self.path.mkdir()  # a directory cannot be read as a file
        warnings: list = []
        load_config(self.path, warnings=warnings)
        self.assertEqual(len(warnings), 1)

    def test_non_object_json_is_reported(self) -> None:
        self.path.write_text("[1, 2, 3]", encoding="utf-8")
        warnings: list = []
        load_config(self.path, warnings=warnings)
        self.assertEqual(len(warnings), 1)
        self.assertIn("settings object", warnings[0])

    def test_a_good_file_produces_no_warning(self) -> None:
        save_config(AppConfig(timeout_seconds=45), self.path)
        warnings: list = []
        load_config(self.path, warnings=warnings)
        self.assertEqual(warnings, [])


class TimeoutBoundsTests(unittest.TestCase):
    """The stored value and the effective value are the same value."""

    def test_out_of_range_values_are_clamped_on_load(self) -> None:
        for stored, expected in ((0, 5), (-1, 5), (1, 5), (99999, 3600)):
            loaded = AppConfig.from_dict({"timeout_seconds": stored})
            self.assertEqual(loaded.timeout_seconds, expected, stored)

    def test_in_range_values_are_kept(self) -> None:
        for stored in (5, 300, 3600):
            self.assertEqual(AppConfig.from_dict({"timeout_seconds": stored}).timeout_seconds, stored)

    def test_unusable_values_fall_back_to_the_default(self) -> None:
        for stored in ("abc", None, [1]):
            loaded = AppConfig.from_dict({"timeout_seconds": stored})
            self.assertEqual(loaded.timeout_seconds, DEFAULT_TIMEOUT_SECONDS, stored)

    def test_stored_value_already_matches_what_the_runner_would_use(self) -> None:
        # The original defect: 99999 was stored as-is and clamped only at call
        # time, so Settings displayed a number the runner never used.
        loaded = AppConfig.from_dict({"timeout_seconds": 99999})
        self.assertEqual(loaded.timeout_seconds, sane_timeout(99999))

    def test_bounds_are_shared_with_the_settings_form(self) -> None:
        self.assertEqual((MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS), (5, 3600))

    def test_extreme_floats_do_not_raise(self) -> None:
        # JSON caps no exponent, so a file containing 1e309 loads as infinity
        # and int(infinity) raises OverflowError — during startup, before any
        # window exists to report it.
        for value in (1e309, float("inf"), float("-inf"), float("nan")):
            self.assertEqual(sane_timeout(value), DEFAULT_TIMEOUT_SECONDS, value)

    def test_a_settings_file_with_an_enormous_timeout_still_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "caplift_ui_config.json"
            path.write_text('{"timeout_seconds": 1e309}', encoding="utf-8")
            warnings: list = []
            loaded = load_config(path, warnings=warnings)
            self.assertEqual(loaded.timeout_seconds, DEFAULT_TIMEOUT_SECONDS)
            self.assertEqual(warnings, [])

    def test_bool_is_not_read_as_a_timeout(self) -> None:
        # int(True) is 1, which would clamp to 5 rather than falling back.
        self.assertEqual(sane_timeout(True), DEFAULT_TIMEOUT_SECONDS)


class ConcurrentSaveTests(unittest.TestCase):
    """Two saves must not share one temporary file."""

    def test_simultaneous_saves_do_not_collide(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "caplift_ui_config.json"
            errors: list = []
            barrier = threading.Barrier(6)

            def worker(index: int) -> None:
                barrier.wait()
                result = save_config(AppConfig(timeout_seconds=10 + index), path)
                if result is not None:
                    errors.append(result)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [])
            # Whoever won, the file is intact and holds one of the values.
            loaded = load_config(path)
            self.assertIn(loaded.timeout_seconds, range(10, 16))

    def test_no_temporary_files_are_left_after_concurrent_saves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            path = directory / "caplift_ui_config.json"
            barrier = threading.Barrier(4)

            def worker(index: int) -> None:
                barrier.wait()
                save_config(AppConfig(timeout_seconds=20 + index), path)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            leftovers = [p.name for p in directory.iterdir() if p.name != path.name]
            self.assertEqual(leftovers, [])


class BooleanSettingTests(unittest.TestCase):
    """An unrecognised value must not silently enable a setting."""

    def test_explicit_words_are_understood(self) -> None:
        for word in ("true", "True", "1", "yes", "on"):
            self.assertTrue(AppConfig.from_dict({"use_huggingface": word}).use_huggingface, word)
        for word in ("false", "False", "0", "no", "off", ""):
            self.assertFalse(AppConfig.from_dict({"use_huggingface": word}).use_huggingface, word)

    def test_the_string_false_is_false(self) -> None:
        # bool("false") is True — the defect this replaces.
        self.assertFalse(AppConfig.from_dict({"use_huggingface": "false"}).use_huggingface)

    def test_real_booleans_pass_through(self) -> None:
        self.assertTrue(AppConfig.from_dict({"use_huggingface": True}).use_huggingface)
        self.assertFalse(AppConfig.from_dict({"use_huggingface": False}).use_huggingface)

    def test_zero_and_one_are_accepted_as_integers(self) -> None:
        self.assertTrue(AppConfig.from_dict({"force_overwrite_by_default": 1}).force_overwrite_by_default)
        self.assertFalse(AppConfig.from_dict({"force_overwrite_by_default": 0}).force_overwrite_by_default)

    def test_other_integers_use_the_fallback(self) -> None:
        for value in (2, -1, 7):
            self.assertFalse(
                AppConfig.from_dict({"force_overwrite_by_default": value}).force_overwrite_by_default,
                value,
            )

    def test_unrecognised_values_use_the_fallback(self) -> None:
        for value in ("maybe", "yep", [], {}, 3.5):
            self.assertFalse(
                AppConfig.from_dict({"use_huggingface": value}).use_huggingface, value
            )

    def test_fallback_can_be_true(self) -> None:
        # The rule is "fallback", not "always False".
        config = AppConfig.from_dict({"use_huggingface": True})
        self.assertTrue(config.use_huggingface)


class CliDiscoveryTests(unittest.TestCase):
    def test_missing_override_falls_back_to_auto_detection(self) -> None:
        # An override that does not exist must not be returned as-is.
        self.assertNotEqual(
            find_cli(r"C:\definitely\not\here\lmstudio-caplift.exe"),
            Path(r"C:\definitely\not\here\lmstudio-caplift.exe"),
        )


if __name__ == "__main__":
    unittest.main()
