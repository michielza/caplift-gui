"""Available-models view: browse unwrapped models and create wrappers."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import customtkinter as ctk

from ..cli_runner import CliRunner
from ..config import resolve_hub_models_dir
from ..models import AvailableModel, RegistryView, WrappedModel
from ..parser import DryRunPreview
from ..templates import TemplateCheck, check_template, find_installed_templates
from .dialogs import ConfirmDialog, MessageDialog, PreviewDialog
from .theme import COLORS, FONTS
from .widgets import DataTable, LabeledCombo, LabeledEntry, SectionCard, StatusPill

COLUMNS = (
    ("model", "Model key", 340),
    ("wrapper", "Suggested wrapper", 260),
    ("base", "Base template", 200),
    ("params", "Size", 110),
)

# Wrapped rows are keyed with a prefix. A model is either available or already
# wrapped, never both, but the prefix guarantees the two maps cannot collide.
WRAPPED_ROW_PREFIX = "wrapped::"


def model_from_wrapped(item: WrappedModel) -> AvailableModel:
    """Present a registry entry in the shape the wrap form expects.

    Deliberately reuses the existing wrapper id: re-wrapping repairs that
    wrapper instead of quietly creating a second one alongside it.
    """
    return AvailableModel(
        model_key=item.model_key,
        wrapper_model_id=item.wrapper_model_id,
        base_model_id=item.base_model_id,
    )


def build_rows(
    available: Sequence[AvailableModel],
    wrapped: Sequence[WrappedModel],
    show_wrapped: bool,
    needle: str = "",
) -> List[Tuple[str, Tuple[str, ...], str]]:
    """Rows for the model table: unwrapped models, then wrappers if asked.

    Pure, so it can be tested without a display. Unwrapped models come first
    because those are the default workflow; already-wrapped ones follow, with
    their own tag so the table can dim them and they cannot be mistaken for new
    work.
    """
    search = (needle or "").strip().lower()
    rows: List[Tuple[str, Tuple[str, ...], str]] = []

    for model in available:
        if search and search not in model.model_key.lower():
            continue
        rows.append(
            (
                model.model_key,
                (
                    model.model_key,
                    model.suggested_wrapper_id,
                    model.base_model_id or "N/A — pick one",
                    model.params_string or "—",
                ),
                "normal" if model.has_base_template else "missing_template",
            )
        )

    if show_wrapped:
        for item in wrapped:
            if search and search not in item.model_key.lower():
                continue
            rows.append(
                (
                    f"{WRAPPED_ROW_PREFIX}{item.wrapper_model_id}",
                    (
                        item.model_key,
                        item.wrapper_model_id,
                        item.base_model_id or "—",
                        # The Size column has no meaning for a registry entry, and
                        # the wrapped view already shows its timestamps.
                        "—",
                    ),
                    "wrapped",
                )
            )

    return rows


class AvailableView(ctk.CTkFrame):
    """Left: installed models. Right: the wrap form for the selected model."""

    def __init__(self, master, app) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app

        self._models: List[AvailableModel] = []
        self._by_key: Dict[str, AvailableModel] = {}
        self._wrapped_rows: Dict[str, WrappedModel] = {}
        self._wrapped_count = 0
        self._show_wrapped = False
        self._selected: Optional[AvailableModel] = None
        self._selected_is_wrapped = False
        self._last_preview: Optional[DryRunPreview] = None
        self._filter_text = ""
        self._hub_dir: Optional[Path] = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_body()

    # ---- construction ---------------------------------------------------

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.grid_columnconfigure(0, weight=1)

        titles = ctk.CTkFrame(header, fg_color="transparent")
        titles.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            titles,
            text="Available models",
            font=FONTS.title,
            text_color=COLORS["text"],
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.count_label = ctk.CTkLabel(
            titles,
            text="Installed models that are not wrapped yet. Refresh needs LM Studio running.",
            font=FONTS.small,
            text_color=COLORS["text_muted"],
            anchor="w",
        )
        self.count_label.grid(row=1, column=0, sticky="w", pady=(2, 0))

        # Wrapped models disappear from the available list once created, so
        # without this there is no way to select one again — and therefore no
        # way to reach --force and repair a wrapper.
        self.wrapped_switch = ctk.CTkSwitch(
            titles,
            text="Show already-wrapped models",
            font=FONTS.small,
            text_color=COLORS["text_muted"],
            progress_color=COLORS["accent"],
            button_color=COLORS["text"],
            button_hover_color=COLORS["accent_hover"],
            command=self._on_show_wrapped_toggled,
        )
        self.wrapped_switch.grid(row=2, column=0, sticky="w", pady=(6, 0))

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e")

        self.search_entry = ctk.CTkEntry(
            actions,
            placeholder_text="Filter model keys…",
            width=240,
            height=32,
            font=FONTS.small,
            fg_color=COLORS["surface_alt"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
        )
        self.search_entry.grid(row=0, column=0, padx=(0, 10))
        self.search_entry.bind("<KeyRelease>", self._on_filter_changed)

        self.hf_switch = ctk.CTkSwitch(
            actions,
            text="Hugging Face metadata",
            font=FONTS.small,
            text_color=COLORS["text_muted"],
            progress_color=COLORS["accent"],
            button_color=COLORS["text"],
            button_hover_color=COLORS["accent_hover"],
            command=self._on_hf_toggled,
        )
        self.hf_switch.grid(row=0, column=1, padx=(0, 12))
        if self.app.app_config.use_huggingface:
            self.hf_switch.select()
        else:
            self.hf_switch.deselect()

        self.refresh_button = ctk.CTkButton(
            actions,
            text="Refresh",
            width=110,
            height=32,
            font=FONTS.body,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color=COLORS["accent_text"],
            command=self.refresh,
        )
        self.refresh_button.grid(row=0, column=2)

    def _build_body(self) -> None:
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2, minsize=400)
        body.grid_rowconfigure(0, weight=1)

        table_card = SectionCard(body, padding=8)
        table_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.table = DataTable(
            table_card.body,
            columns=COLUMNS,
            on_select=self._on_row_selected,
        )
        self.table.grid(row=0, column=0, sticky="nsew")
        table_card.body.grid_rowconfigure(0, weight=1)

        self.wrap_card = SectionCard(
            body,
            title="Create wrapper",
            subtitle="Copies a Hub model profile and repoints it at the selected model.",
            subtitle_wraplength=330,
        )
        self.wrap_card.grid(row=0, column=1, sticky="nsew")
        self.wrap_card.body.grid_rowconfigure(0, weight=1)

        # Scrollable: the form must not clip at small window heights or at the
        # higher DPI scaling Windows applies on large displays.
        panel = ctk.CTkScrollableFrame(self.wrap_card.body, fg_color="transparent")
        panel.grid(row=0, column=0, sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)
        row = 0

        self.model_title = ctk.CTkLabel(
            panel,
            text="Select a model from the list.",
            font=FONTS.body_bold,
            text_color=COLORS["text_muted"],
            anchor="w",
            justify="left",
            wraplength=340,
        )
        self.model_title.grid(row=row, column=0, sticky="ew")
        row += 1

        self.model_label = ctk.CTkLabel(
            panel,
            text="",
            font=FONTS.mono_small,
            text_color=COLORS["text_dim"],
            anchor="w",
            justify="left",
            wraplength=340,
        )
        self.model_label.grid(row=row, column=0, sticky="ew", pady=(2, 0))
        row += 1

        self.model_meta = ctk.CTkLabel(
            panel,
            text="",
            font=FONTS.small,
            text_color=COLORS["text_dim"],
            anchor="w",
            justify="left",
            wraplength=340,
        )
        self.model_meta.grid(row=row, column=0, sticky="ew", pady=(4, 0))
        row += 1

        self.base_field = LabeledCombo(
            panel,
            label="Base template (--base-model-id)",
            hint="Capability profile to copy, in owner/name form.",
            hint_wraplength=340,
            on_change=self._on_fields_changed,
        )
        self.base_field.grid(row=row, column=0, sticky="ew", pady=(12, 0))
        row += 1

        self.wrapper_field = LabeledEntry(
            panel,
            label="Wrapper id (--wrapper-model-id)",
            hint="Must not equal the model key, or LM Studio hides it as a circular dependency.",
            placeholder="local/name",
            hint_wraplength=340,
        )
        self.wrapper_field.grid(row=row, column=0, sticky="ew", pady=(12, 0))
        self.wrapper_field.bind_change(self._on_fields_changed)
        row += 1

        self.hf_field = LabeledEntry(
            panel,
            label="Hugging Face repo (--hf-repo, optional)",
            hint="Exact source repo, e.g. unsloth/Qwen3.5-35B-A3B-GGUF.",
            placeholder="owner/repo",
            hint_wraplength=340,
        )
        self.hf_field.grid(row=row, column=0, sticky="ew", pady=(12, 0))
        row += 1

        self.force_switch = ctk.CTkSwitch(
            panel,
            text="Allow overwriting existing files (--force)",
            font=FONTS.small,
            text_color=COLORS["text_muted"],
            progress_color=COLORS["warn"],
            button_color=COLORS["text"],
            button_hover_color=COLORS["accent_hover"],
        )
        self.force_switch.grid(row=row, column=0, sticky="w", pady=(14, 0))
        if self.app.app_config.force_overwrite_by_default:
            self.force_switch.select()
        row += 1

        self.validation_label = ctk.CTkLabel(
            panel,
            text="",
            font=FONTS.small,
            text_color=COLORS["error"],
            anchor="w",
            justify="left",
            wraplength=360,
        )
        self.validation_label.grid(row=row, column=0, sticky="ew", pady=(10, 0))
        self.validation_label.grid_remove()
        row += 1

        buttons = ctk.CTkFrame(panel, fg_color="transparent")
        buttons.grid(row=row, column=0, sticky="ew", pady=(16, 0))
        buttons.grid_columnconfigure(0, weight=1)

        self.preview_button = ctk.CTkButton(
            buttons,
            text="Preview (dry run)",
            height=36,
            font=FONTS.body,
            fg_color="transparent",
            hover_color=COLORS["surface_hi"],
            text_color=COLORS["text"],
            border_width=1,
            border_color=COLORS["border_hi"],
            state="disabled",
            command=self.preview_selected,
        )
        self.preview_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.create_button = ctk.CTkButton(
            buttons,
            text="Create wrapper",
            height=36,
            font=FONTS.body_bold,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color=COLORS["accent_text"],
            state="disabled",
            command=self.create_selected,
        )
        self.create_button.grid(row=0, column=1, sticky="ew")

        self.state_pill = StatusPill(panel, text="No selection", tone="neutral")
        self.state_pill.grid(row=row + 1, column=0, sticky="w", pady=(12, 0))

        self._set_form_enabled(False)
        self.refresh_template_choices()

    def on_shown(self) -> None:
        """Re-scan installed templates: the hub directory can change in Settings."""
        self.refresh_template_choices()

    def refresh_template_choices(self) -> None:
        """Fill the base-template dropdown from the hub models directory.

        Official Hub models come first because those are the ones worth copying
        from; wrappers keep working but are listed after. Recently used ids are
        appended so a template the user typed earlier is not lost from the list.
        """
        hub_dir = resolve_hub_models_dir(self.app.app_config.hub_models_dir)
        self._hub_dir = hub_dir
        templates = find_installed_templates(hub_dir)
        groups = (
            [t.model_id for t in templates if not t.is_wrapper],
            [t.model_id for t in templates if t.is_wrapper],
            [m for m in self.app.app_config.recent_base_templates if m],
        )
        values: List[str] = []
        for group in groups:
            for model_id in group:
                if model_id not in values:
                    values.append(model_id)
        self.base_field.set_values(values)
        self._update_base_hint()

    def _template_check(self) -> TemplateCheck:
        return check_template(self._hub_dir, self.base_field.get())

    def _update_base_hint(self) -> None:
        """Say whether the current base template is actually installed.

        Mirrors the CLI's own test, so a typo is caught here instead of coming
        back as a one-line error after a subprocess round trip.
        """
        if not self.base_field.get():
            self.base_field.reset_hint()
            return
        check = self._template_check()
        if not check.checked:
            self.base_field.set_hint(
                "Could not find the hub models directory, so this was not verified.",
                "muted",
            )
        elif check.found:
            self.base_field.set_hint(f"Installed at {check.path}", "ok")
        else:
            self.base_field.set_hint(check.reason, "error")

    # ---- data loading ---------------------------------------------------

    def refresh(self) -> None:
        """Reload the installed-model list (requires LM Studio for ``--all``)."""
        use_hf = bool(self.hf_switch.get())
        self.refresh_button.configure(state="disabled", text="Loading…")
        self.app.log("list --all --json", "command")

        def work():
            runner: CliRunner = self.app.build_runner()
            return runner.list_registry(include_available=True, use_huggingface=use_hf)

        def done(registry):
            self.refresh_button.configure(state="normal", text="Refresh")
            self.set_registry(registry)
            self.app.on_registry_loaded(registry)
            self.app.log(
                f"Loaded {registry.available_count} available and {registry.wrapped_count} wrapped model(s).",
                "ok",
            )

        def failed(exc):
            self.refresh_button.configure(state="normal", text="Refresh")
            self.app.report_error("Could not list models", exc)
            self.count_label.configure(
                text="Could not load the model list. See Output below.",
                text_color=COLORS["warn"],
            )

        self.app.run_task(work, on_success=done, on_error=failed, label="list models")

    def set_registry(self, registry: RegistryView) -> None:
        """Store both halves of the listing and re-render."""
        self._models = list(registry.available)
        self._by_key = {model.model_key: model for model in self._models}
        self._wrapped_rows = {
            f"{WRAPPED_ROW_PREFIX}{item.wrapper_model_id}": item for item in registry.wrapped
        }
        self._wrapped_count = registry.wrapped_count
        self._selected = None
        self._selected_is_wrapped = False
        self._last_preview = None
        self._set_form_enabled(False)
        self._render_rows()
        self._render_summary()

    def _on_show_wrapped_toggled(self) -> None:
        self._show_wrapped = bool(self.wrapped_switch.get())
        self._render_rows()
        self._render_summary()
        self.app.log(
            f"Already-wrapped models {'shown' if self._show_wrapped else 'hidden'}.",
            "info",
        )

    def _render_summary(self) -> None:
        """Summary line under the title, kept truthful about the toggle state."""
        total = len(self._models)
        missing = sum(1 for model in self._models if not model.has_base_template)
        if total == 0:
            message = "Nothing to wrap: no unwrapped LLMs are installed."
        else:
            message = f"{total} model(s) without a wrapper"
            if missing:
                message += f" · {missing} need an explicit base template"
        if self._wrapped_count:
            state = "shown below" if self._show_wrapped else "hidden"
            message += f" · {self._wrapped_count} already wrapped, {state}"
        self.count_label.configure(text=message, text_color=COLORS["text_muted"])

    def _render_rows(self) -> None:
        rows = build_rows(
            self._models,
            list(self._wrapped_rows.values()),
            self._show_wrapped,
            self._filter_text,
        )
        self.table.set_rows(rows)
        if self._filter_text:
            self.count_label.configure(
                text=f"Showing {len(rows)} of {len(self._models) + self._wrapped_count} model(s).",
                text_color=COLORS["text_muted"],
            )

    def _on_filter_changed(self, _event=None) -> None:
        self._filter_text = self.search_entry.get()
        self._render_rows()

    def _on_hf_toggled(self) -> None:
        self.app.app_config.use_huggingface = bool(self.hf_switch.get())
        self.app.save_config()
        hint = "on — refresh will fetch model cards" if self.hf_switch.get() else "off"
        self.app.log(f"Hugging Face metadata {hint}.", "info")

    # ---- selection ------------------------------------------------------

    def _on_row_selected(self, row_id: Optional[str]) -> None:
        if not row_id:
            self._selected = None
            self._selected_is_wrapped = False
            self._set_form_enabled(False)
            self.state_pill.set_state("No selection", "neutral")
            return

        if row_id in self._by_key:
            model = self._by_key[row_id]
            wrapped_entry = None
        elif row_id in self._wrapped_rows:
            wrapped_entry = self._wrapped_rows[row_id]
            model = model_from_wrapped(wrapped_entry)
        else:
            self._selected = None
            self._selected_is_wrapped = False
            self._set_form_enabled(False)
            self.state_pill.set_state("No selection", "neutral")
            return

        self._selected = model
        self._selected_is_wrapped = wrapped_entry is not None
        self._last_preview = None

        self.model_title.configure(
            text=model.display_name or model.model_key,
            text_color=COLORS["text"],
        )
        self.model_label.configure(text=model.model_key, text_color=COLORS["text_dim"])
        if wrapped_entry is not None:
            meta = (
                f"Already wrapped as {wrapped_entry.wrapper_model_id}\n"
                f"updated {wrapped_entry.updated_display}"
            )
            self.force_switch.select()
        else:
            meta = "\n".join(line for line in (model.summary, model.path) if line)
        self.model_meta.configure(text=meta)

        # Enable first: a disabled entry ignores writes, so populating before
        # this point would leave the fields looking empty.
        self._set_form_enabled(True)
        self.base_field.set(model.base_model_id or self.app.last_base_template() or "")
        self.wrapper_field.set(model.suggested_wrapper_id)
        self.hf_field.set(model.hf_repo or "")

        if wrapped_entry is not None:
            self.state_pill.set_state("Already wrapped — recreating will need --force", "warn")
        elif model.has_base_template:
            self.state_pill.set_state(f"Base template suggested: {model.base_model_id}", "accent")
        else:
            self.state_pill.set_state("No static match — set a base template", "warn")
        self._on_fields_changed()

    def _set_form_enabled(self, enabled: bool) -> None:
        for field in (self.base_field, self.wrapper_field, self.hf_field):
            field.set_enabled(enabled)
        self.force_switch.configure(state="normal" if enabled else "disabled")
        self.preview_button.configure(state="normal" if enabled else "disabled")
        self.create_button.configure(state="normal" if enabled else "disabled")
        if not enabled:
            self.model_title.configure(text="Select a model from the list.", text_color=COLORS["text_muted"])
            self.model_label.configure(text="")
            self.model_meta.configure(text="")

    # ---- validation -----------------------------------------------------

    def _on_fields_changed(self) -> None:
        """Live-validate the form: blockers disable the buttons, warnings do not."""
        self._update_base_hint()
        if self._selected is None:
            return

        blockers = self.collect_blockers()
        problems = self.collect_problems()

        if blockers:
            self.validation_label.configure(text=blockers[0], text_color=COLORS["error"])
            self.validation_label.grid()
            self.create_button.configure(state="disabled")
            self.preview_button.configure(state="disabled")
            return

        self.create_button.configure(state="normal")
        self.preview_button.configure(state="normal")
        if problems:
            self.validation_label.configure(text=problems[0], text_color=COLORS["warn"])
            self.validation_label.grid()
        else:
            self.validation_label.grid_remove()

    def collect_problems(self) -> List[str]:
        """Warnings that do not stop a dry run."""
        notes: List[str] = []
        if self._selected is None:
            return notes
        base = self.base_field.get()
        if not base:
            notes.append(
                "No base template set. The CLI will try to match one itself and will fail "
                "if it cannot — set one explicitly to be safe."
            )
        wrapper = self.wrapper_field.get()
        if wrapper and base and wrapper == base:
            # Not the circular-dependency case (that is wrapper == model key,
            # which is a blocker below). This one targets the template's own
            # directory, so it could overwrite the model it copies from.
            notes.append(
                f"Wrapper id and base template are both {wrapper}. The wrapper would be written "
                "into that model's own folder, risking the template it copies from — use a local/ name."
            )
        if wrapper and "/" not in wrapper:
            notes.append("Wrapper id should look like owner/name.")
        return notes

    def collect_blockers(self) -> List[str]:
        """Errors that make the wrap invalid before it is even attempted."""
        problems: List[str] = []
        if self._selected is None:
            return ["No model selected."]
        base = self.base_field.get()
        model_key = self._selected.model_key
        if base and base == model_key:
            problems.append(
                "The base template equals the model key. That creates a circular dependency "
                "and LM Studio will hide the wrapper. Use a different wrapper id or base template."
            )
        wrapper = self.wrapper_field.get()
        if wrapper and wrapper == model_key:
            problems.append(
                "Wrapper id equals the model key. LM Studio requires model != base.key; pick a local/ name."
            )
        # A base template that is not installed makes the CLI fail outright, so
        # it is a blocker rather than a warning. Skipped entirely when no hub
        # directory could be located: not knowing is not evidence of absence.
        check = self._template_check()
        if base and check.checked and not check.found:
            problems.append(check.reason)
        # Re-wrapping targets a directory that already holds manifest.json and
        # model.yaml, so the CLI refuses without --force. Requiring it up front
        # beats letting the attempt fail.
        if self._selected_is_wrapped and not self.force_switch.get():
            problems.append(
                "This model is already wrapped, so its files exist at the target. "
                "Tick “Allow overwriting existing files” to recreate the wrapper."
            )
        return problems

    # ---- actions --------------------------------------------------------

    def preview_selected(self) -> None:
        model = self._selected
        if model is None:
            return
        blockers = self.collect_blockers()
        if blockers:
            MessageDialog.show(self.app, "Cannot preview", blockers[0], tone="error")
            return

        base = self.base_field.get() or None
        wrapper = self.wrapper_field.get() or None
        hf_repo = self.hf_field.get() or None

        def work():
            runner: CliRunner = self.app.build_runner()
            return runner.preview_wrap(
                model_key=model.model_key,
                wrapper_model_id=wrapper,
                base_model_id=base,
                hf_repo=hf_repo,
            )

        def done(preview: DryRunPreview):
            self._last_preview = preview
            self.app.log(f"$ wrap {model.model_key} --dry-run", "command")
            self.app.log(
                f"{len(preview.files)} file(s) would be written to "
                f"{preview.target_dir or 'the hub models directory'}",
                "ok" if preview.files else "warn",
            )
            PreviewDialog.show(self.app, preview, heading="Dry run preview")
            if preview.wrapper_model_id and preview.wrapper_model_id != self.wrapper_field.get():
                self.wrapper_field.set(preview.wrapper_model_id)
                self.app.log(f"Wrapper id confirmed by CLI: {preview.wrapper_model_id}", "info")

        self.app.run_task(work, on_success=done, on_error=lambda exc: self.app.report_error("Dry run failed", exc), label="dry run")

    def create_selected(self) -> None:
        model = self._selected
        if model is None:
            return
        blockers = self.collect_blockers()
        if blockers:
            MessageDialog.show(self.app, "Cannot create wrapper", blockers[0], tone="error")
            return

        base = self.base_field.get() or None
        wrapper = self.wrapper_field.get() or None
        hf_repo = self.hf_field.get() or None
        force = bool(self.force_switch.get())

        details = [
            f"model key:      {model.model_key}",
            f"wrapper id:     {wrapper or '(CLI default)'}",
            f"base template:  {base or '(CLI auto-match)'}",
        ]
        if hf_repo:
            details.append(f"hf repo:        {hf_repo}")
        if self._last_preview is not None:
            if self._last_preview.target_dir:
                details.append(f"target dir:     {self._last_preview.target_dir}")
            if self._last_preview.registry_path:
                details.append(f"registry:       {self._last_preview.registry_path}")
        details.append(f"mode:           {'overwrite existing files' if force else 'refuse to overwrite'}")

        if not ConfirmDialog.ask(
            self.app,
            title="Create wrapper",
            body=(
                "Write the wrapper model files and update the caplift registry?"
                if force
                else "Write the wrapper model files and update the caplift registry? "
                "Existing files at the target will not be replaced."
            ),
            detail_lines=details,
            confirm_text="Create wrapper",
            danger=force,
        ):
            self.app.log("Wrap cancelled.", "info")
            return

        def work():
            runner: CliRunner = self.app.build_runner()
            return runner.wrap(
                model_key=model.model_key,
                wrapper_model_id=wrapper,
                base_model_id=base,
                hf_repo=hf_repo,
                force=force,
            )

        def done(result):
            self.app.log(f"$ {result.command_line}", "command")
            if result.stdout.strip():
                self.app.log(result.stdout.strip(), "stdout")
            if result.stderr.strip():
                self.app.log(result.stderr.strip(), "stderr")
            self.app.log("Wrapper created. Restart LM Studio, then select the local/… model.", "ok")
            if base:
                self.app.app_config.remember("recent_base_templates", base)
            if hf_repo:
                self.app.app_config.remember("recent_hf_repos", hf_repo)
            self.app.save_config()
            self.app.notify_wrappers_changed()
            MessageDialog.show(
                self.app,
                "Wrapper created",
                f"{wrapper or model.model_key} is ready. Restart LM Studio to see it under local/ models.",
                detail_lines=[result.stdout.strip()] if result.stdout.strip() else [],
                tone="ok",
            )
            self.refresh()

        self.app.run_task(work, on_success=done, on_error=lambda exc: self.app.report_error("Wrap failed", exc), label="wrap")
