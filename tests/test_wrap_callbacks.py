"""Regression tests for the Create and Preview callbacks without a desktop."""

import unittest
from unittest.mock import Mock, patch

from caplift_ui.cli_runner import CliCommandError, CliResult
from caplift_ui.models import AvailableModel
from caplift_ui.parser import DryRunPreview
from caplift_ui.ui.available_view import AvailableView


class WrapCallbackTests(unittest.TestCase):
    def setUp(self):
        self.view = Mock()
        self.view._selected = AvailableModel(model_key="example/model-a")
        self.view._last_preview = None
        context = getattr(AvailableView, "_preview_context", None)
        if context is not None:
            self.view._preview_context.side_effect = lambda: context(self.view)
        self.view.collect_blockers.return_value = []
        self.view.base_field.get.return_value = "library/template"
        self.view.wrapper_field.get.return_value = "local/model-a"
        self.view._hf_repo_for_wrap.return_value = None
        self.view.force_switch.get.return_value = False

    @patch("caplift_ui.ui.available_view.ConfirmDialog.ask", return_value=True)
    def test_nonzero_create_exit_reaches_error_callback(self, _confirm):
        result = CliResult(["wrap"], 1, "", "synthetic failure")
        self.view.app.build_runner.return_value.wrap.return_value = result

        AvailableView.create_selected(self.view)
        args, callbacks = self.view.app.run_task.call_args
        with self.assertRaises(CliCommandError) as failure:
            args[0]()
        self.assertIs(failure.exception.result, result)
        callbacks["on_error"](failure.exception)
        self.view.app.report_error.assert_called_once_with("Wrap failed", failure.exception)
        self.view.refresh.assert_not_called()

    @patch("caplift_ui.ui.available_view.PreviewDialog.show")
    def test_old_preview_cannot_change_another_selected_model(self, dialog):
        AvailableView.preview_selected(self.view)
        done = self.view.app.run_task.call_args.kwargs["on_success"]
        self.view._selected = AvailableModel(model_key="example/model-b")
        self.view.wrapper_field.get.return_value = "local/model-b"

        done(DryRunPreview(wrapper_model_id="local/model-a"))

        dialog.assert_not_called()
        self.view.wrapper_field.set.assert_not_called()

    @patch("caplift_ui.ui.available_view.PreviewDialog.show")
    @patch("caplift_ui.ui.available_view.ConfirmDialog.ask", return_value=False)
    def test_create_confirmation_keeps_target_only_for_matching_preview(self, confirm, _dialog):
        AvailableView.preview_selected(self.view)
        done = self.view.app.run_task.call_args.kwargs["on_success"]
        done(DryRunPreview(wrapper_model_id="local/model-a", target_dir="example-target"))

        AvailableView.create_selected(self.view)
        self.assertIn("example-target", str(confirm.call_args.kwargs["detail_lines"]))
        self.view.wrapper_field.get.return_value = "local/model-b"

        AvailableView.create_selected(self.view)
        self.assertNotIn("example-target", str(confirm.call_args.kwargs["detail_lines"]))
