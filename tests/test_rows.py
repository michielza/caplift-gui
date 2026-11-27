"""Tests for the model-table row building.

``build_rows`` and ``model_from_wrapped`` are pure functions, so the logic that
decides what the table shows — and which entries can be re-wrapped — is testable
without opening a window.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from caplift_ui.models import AvailableModel, WrappedModel
from caplift_ui.ui.available_view import (
    UNKNOWN_SOURCE_KEY,
    WRAPPED_ROW_PREFIX,
    build_rows,
    hf_repo_for_wrap,
    model_from_wrapped,
)


def available(model_key: str, base: str | None = "qwen/qwen3.8-27b", wrapper: str | None = None, params: str | None = "27B") -> AvailableModel:
    return AvailableModel(
        model_key=model_key,
        base_model_id=base,
        wrapper_model_id=wrapper,
        params_string=params,
    )


def wrapped(model_key: str, wrapper_id: str, base: str | None = "qwen/qwen3.8-27b") -> WrappedModel:
    return WrappedModel(
        wrapper_model_id=wrapper_id,
        model_key=model_key,
        base_model_id=base,
        updated_at_unix_seconds=1795206747,
    )


class BuildRowsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.models = [available("granite-4.2-30b"), available("laguna-xs-2.1", base=None)]
        self.wrapped = [wrapped("qwen3.8-27b-uncensored", "local/qwen3-8-27b-uncensored")]

    def test_wrapped_rows_are_hidden_by_default(self) -> None:
        rows = build_rows(self.models, self.wrapped, show_wrapped=False)
        self.assertEqual([row[0] for row in rows], ["granite-4.2-30b", "laguna-xs-2.1"])

    def test_wrapped_rows_appear_when_asked(self) -> None:
        rows = build_rows(self.models, self.wrapped, show_wrapped=True)
        self.assertEqual(len(rows), 3)
        # Unwrapped models stay first: they are the default workflow.
        self.assertEqual(
            [row[0] for row in rows],
            ["granite-4.2-30b", "laguna-xs-2.1", f"{WRAPPED_ROW_PREFIX}local/qwen3-8-27b-uncensored"],
        )

    def test_wrapped_rows_are_tagged_and_prefixed(self) -> None:
        rows = build_rows([], self.wrapped, show_wrapped=True)
        row_id, _values, tag = rows[0]
        self.assertEqual(tag, "wrapped")
        self.assertTrue(row_id.startswith(WRAPPED_ROW_PREFIX))
        # The row id must not collide with an available model key, or selecting
        # the wrong entry would populate the form.
        self.assertNotEqual(row_id, self.wrapped[0].model_key)

    def test_missing_base_template_is_tagged(self) -> None:
        rows = build_rows(self.models, [], show_wrapped=False)
        self.assertEqual(rows[0][2], "normal")
        self.assertEqual(rows[1][2], "missing_template")
        self.assertIn("N/A", rows[1][1][2])

    def test_filter_applies_to_both_groups(self) -> None:
        rows = build_rows(self.models, self.wrapped, show_wrapped=True, needle="qwen")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0][0].startswith(WRAPPED_ROW_PREFIX))

    def test_filter_is_case_insensitive(self) -> None:
        rows = build_rows(self.models, [], show_wrapped=False, needle="GRANITE")
        self.assertEqual([row[0] for row in rows], ["granite-4.2-30b"])

    def test_filter_with_no_matches_yields_nothing(self) -> None:
        self.assertEqual(build_rows(self.models, self.wrapped, True, "zzz"), [])

    def test_size_column_is_blank_for_registry_entries(self) -> None:
        # The Size column has no meaning for a wrapper, so it must not invent one.
        rows = build_rows([], self.wrapped, show_wrapped=True)
        self.assertEqual(rows[0][1][3], "—")

    def test_empty_inputs(self) -> None:
        self.assertEqual(build_rows([], [], False), [])
        self.assertEqual(build_rows([], [], True), [])


class ModelFromWrappedTests(unittest.TestCase):
    def test_reuses_the_existing_wrapper_id(self) -> None:
        # Re-wrapping must repair the existing wrapper, not create a second one.
        item = wrapped("qwen3.8-27b-uncensored", "local/qwen3-8-27b-uncensored")
        model = model_from_wrapped(item)
        self.assertEqual(model.model_key, "qwen3.8-27b-uncensored")
        self.assertEqual(model.suggested_wrapper_id, "local/qwen3-8-27b-uncensored")
        self.assertEqual(model.base_model_id, "qwen/qwen3.8-27b")

    def test_carries_the_base_template_for_repair(self) -> None:
        item = wrapped("some/model", "local/some-model", base="meta/muse-glimmer")
        self.assertEqual(model_from_wrapped(item).base_model_id, "meta/muse-glimmer")

    def test_unknown_metadata_stays_unknown(self) -> None:
        # The registry holds no publisher or size, so those must not be invented.
        model = model_from_wrapped(wrapped("some/model", "local/some-model"))
        self.assertIsNone(model.params_string)
        self.assertIsNone(model.publisher)
        self.assertEqual(model.summary, "")

    def test_derives_a_wrapper_id_when_the_registry_lacks_one(self) -> None:
        item = WrappedModel(wrapper_model_id="", model_key="granite-4.2-30b")
        self.assertEqual(model_from_wrapped(item).suggested_wrapper_id, "local/granite-4-2-30b")


class SearchWithMissingSourceKeyTests(unittest.TestCase):
    """A wrapped entry may have no source model key recorded.

    Regression: the search compared ``item.model_key.lower()`` directly, so a
    missing key raised ``AttributeError`` while typing in the filter box.
    """

    def setUp(self) -> None:
        self.keyless = WrappedModel(wrapper_model_id="local/no-source-key")

    def test_search_does_not_raise_without_a_source_key(self) -> None:
        rows = build_rows([], [self.keyless], show_wrapped=True, needle="anything")
        self.assertEqual(rows, [])

    def test_row_is_still_shown_when_not_filtering(self) -> None:
        rows = build_rows([], [self.keyless], show_wrapped=True)
        self.assertEqual(len(rows), 1)
        cells = rows[0][1]
        self.assertEqual(cells[0], UNKNOWN_SOURCE_KEY)
        self.assertEqual(cells[1], "local/no-source-key")

    def test_placeholder_is_searchable(self) -> None:
        # It is what the table displays, so searching for it must find the row
        # rather than silently matching nothing.
        rows = build_rows([], [self.keyless], show_wrapped=True, needle="not recorded")
        self.assertEqual(len(rows), 1)

    def test_model_from_wrapped_never_yields_a_none_key(self) -> None:
        model = model_from_wrapped(self.keyless)
        self.assertEqual(model.model_key, UNKNOWN_SOURCE_KEY)
        self.assertEqual(model.suggested_wrapper_id, "local/no-source-key")


class HfRepoForWrapTests(unittest.TestCase):
    """--hf-repo also steers the CLI's template matching, so a guess must not.

    Observed against the real CLI: with a blank base template, adding
    --hf-repo changed the outcome from "no suitable static base template found"
    to "base template qwen/qwen3-30b-a3b is not installed" — the flag demonstrably
    redirects template selection.
    """

    def test_withheld_when_no_base_template(self) -> None:
        self.assertIsNone(hf_repo_for_wrap("", "owner/repo"))

    def test_whitespace_base_template_is_still_empty(self) -> None:
        self.assertIsNone(hf_repo_for_wrap("   ", "owner/repo"))

    def test_sent_once_a_base_template_is_set(self) -> None:
        self.assertEqual(hf_repo_for_wrap("qwen/qwen3.8-27b", "owner/repo"), "owner/repo")

    def test_nothing_is_sent_when_the_field_is_blank(self) -> None:
        self.assertIsNone(hf_repo_for_wrap("qwen/qwen3.8-27b", ""))

    def test_surrounding_whitespace_is_trimmed(self) -> None:
        self.assertEqual(hf_repo_for_wrap("qwen/qwen3.8-27b", " owner/repo "), "owner/repo")


if __name__ == "__main__":
    unittest.main()
