"""Contract tests for the UI layer that need no display.

These introspect the dialog classes instead of opening windows, so they run
headless with the rest of the suite.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from caplift_ui.ui import dialogs

UI_DIR = Path(__file__).resolve().parent.parent / "caplift_ui" / "ui"

# Matches XDialog.ask( / XDialog.show( at any call site.
CALL_RE = re.compile(r"\b(?P<cls>[A-Z]\w*Dialog)\.(?P<method>ask|show)\s*\(")


class DialogMethodContractTests(unittest.TestCase):
    """Every ``XDialog.method(...)`` call site must exist on that class.

    A mistyped classmethod is invisible until the exact branch runs, and then it
    raises inside a Tk callback where nothing reports it. That is how a call to
    a non-existent ``MessageDialog.ask`` shipped for the "save anyway?"
    confirmation paths in Settings.
    """

    def test_called_dialog_classmethods_exist(self) -> None:
        problems: list[str] = []
        for path in sorted(UI_DIR.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            for match in CALL_RE.finditer(source):
                cls_name = match.group("cls")
                method = match.group("method")
                dialog_class = getattr(dialogs, cls_name, None)
                if dialog_class is None:
                    problems.append(f"{path.name}: {cls_name} is not defined in dialogs.py")
                elif not callable(getattr(dialog_class, method, None)):
                    problems.append(f"{path.name}: {cls_name}.{method}() does not exist")

        self.assertEqual(problems, [], "dialog call sites do not match dialogs.py")

    def test_confirm_dialog_exposes_ask(self) -> None:
        # The settings and wrap flows depend on this returning a bool.
        self.assertTrue(callable(getattr(dialogs.ConfirmDialog, "ask", None)))

    def test_all_dialogs_subclass_the_shared_base(self) -> None:
        for name in ("ConfirmDialog", "PreviewDialog", "MessageDialog"):
            dialog_class = getattr(dialogs, name)
            self.assertTrue(issubclass(dialog_class, dialogs._BaseDialog), name)


if __name__ == "__main__":
    unittest.main()
