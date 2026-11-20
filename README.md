# Caplift

A desktop UI for **`lmstudio-caplift`** — the tool that gives third-party LM Studio models the
app-side capabilities of comparable Hub models (thinking controls, tool-use profiles, prompt
templates).

Dark, minimal, and dependency-light: one window, three views, no accounts, no telemetry.

## What it does

- **Available models** — lists installed LLMs that are not wrapped yet, with the CLI's suggested
  base template for each. Select one, adjust the options, preview the generated files, then create
  the wrapper.
- **Wrapped models** — shows everything tracked in `.lmstudio-caplift.json`, including the target
  folder and registry entry for each wrapper.
- **Settings** — where the CLI lives, the LM Studio hub directory, the `lms` executable, and the
  command timeout.

Only `list` and `wrap` are wired up so far. The other subcommands (`enable-thinking`, and anything
added later) are a nav entry plus a view away — see [Adding a view](#adding-a-view).

## Requirements

- Windows 10/11
- Python 3.9+ — **only to build or run from source**; the built executable bundles its own runtime
- LM Studio, running, for the **Available models** list (that list comes from `lms ls --json`)
- `lmstudio-caplift.exe` **in the same folder as this app**

The **Wrapped models** list works without LM Studio running, since it only reads the caplift
registry — so the UI is still useful when LM Studio is closed.

## Getting `lmstudio-caplift.exe`

This UI is a front end; it does not ship or reimplement the CLI. Obtain `lmstudio-caplift.exe`
separately, then place it next to the UI executable:

```text
somewhere\
  lmstudio-caplift.exe     <- the CLI
  caplift-ui.exe           <- this project
```

<!-- TODO: link this to the lmstudio-caplift repository (and its Releases page) once it is public. -->

The UI looks for `lmstudio-caplift.exe` in its own directory. If you need to keep the two apart, set
an explicit path under **Settings → Override path**.

## Install

No prebuilt binary is published yet, so build it (see [Build from source](#build-from-source)). Then:

1. Put `caplift-ui.exe` in the same folder as `lmstudio-caplift.exe`.
2. Run `caplift-ui.exe`.

## Using it

1. Start LM Studio. Press **Refresh** on the Available models view.
2. Pick a model. The right-hand panel fills in:
   - **Base template** — the capability profile to copy, and the one field worth understanding:
     it must be an **LM Studio Hub model that is already installed**, because the wrapper is built
     by copying that model's `manifest.json` and `model.yaml`. The field is a dropdown built by
     scanning your hub models directory — official models first, caplift wrappers after — but you
     can still type any `owner/name` by hand. Whatever you enter is checked against that directory,
     so a template that is not installed is reported *before* the CLI is invoked (and Create is
     blocked, since the CLI would fail outright). Rows where the CLI found no match show
     `N/A — pick one`.
   - **Wrapper id** — the `local/...` id the wrapper will be registered under. It must not equal the
     model key, or LM Studio hides it as a circular dependency. The UI blocks that case before it
     reaches the CLI.
   - **Hugging Face repo** — optional. Recorded as the wrapper's source in the generated files, so
     the model is not presented as an anonymous local artifact. Pre-filled by deriving `owner/repo`
     from the installed file path (`lms ls` reports each model that way), which is correct for
     anything installed from Hugging Face; edit or clear it if that is not its source. It is only
     sent once a base template is set, because the CLI also uses this flag to pick a template — and
     this value is a derivation, not something the CLI verifies.
3. **Preview (dry run)** first. Nothing is written. You get the exact `manifest.json` and `model.yaml`
   that would be generated.
4. **Create wrapper**. A confirmation lists the target directory and registry path, then the CLI runs.
5. Restart LM Studio and select the `local/...` model.
6. **To repair or recreate a wrapper**, tick **Show already-wrapped models**. A wrapped model leaves
   the available list once it is created, so this is the only way to select it again. The form then
   pre-fills with that wrapper's existing id and base template, and *Allow overwriting* is ticked for
   you — re-wrapping replaces the files at that target, which is what you want when a wrapper was
   built from the wrong template. Untick it and the UI blocks the attempt rather than letting the CLI
   refuse.

## Settings

Stored in `caplift_ui_config.json`, next to the executable. Delete it to reset.

| Setting | Meaning |
| --- | --- |
| Override path | Explicit path to `lmstudio-caplift.exe`. Blank = same folder as the UI. |
| Hub models directory | `--hub-models-dir`. Blank = `%USERPROFILE%\.lmstudio\hub\models`. |
| `lms` executable | `--lms`. Blank = `%USERPROFILE%\.lmstudio\bin\lms.exe`, then `PATH`. |
| Command timeout | How long to wait for the CLI before giving up. |
| Allow overwriting by default | Pre-ticks `--force` on the wrap form. Off by default, deliberately. |

`--force` replaces an existing `manifest.json` / `model.yaml`, so the confirmation dialog turns red
and says so when it is enabled.

## Keyboard shortcuts

| Key | Action |
| --- | --- |
| `Ctrl+1` / `Ctrl+2` / `Ctrl+3` | Available models / Wrapped models / Settings |
| `Ctrl+R`, `F5` | Refresh the current view |
| `Ctrl+Q` | Quit |

## Build from source

```sh
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

python -m unittest discover -s tests -t .     # unit tests, no GUI required
.venv\Scripts\python.exe main.py              # run from source
```

Build a single executable (bundles the Python runtime):

```sh
build.bat            # -> dist\caplift-ui.exe
build.bat deploy     # also copies it next to ..\lmstudio-caplift.exe
```

## Layout

```text
main.py                     entry point (also the PyInstaller target)
main.spec                   one-file, windowed build
build.bat                   venv + tests + build (+ optional deploy)
caplift_ui/
  config.py                 exe discovery, config file load/save
  models.py                 AvailableModel / WrappedModel / RegistryView
  parser.py                 tolerant parsers for CLI JSON and dry-run output
  cli_runner.py             subprocess wrapper around the CLI
  tasks.py                  worker threads + main-thread callbacks for Tk
  ui/
    app.py                  main window, nav, console, status bar
    theme.py                colours and fonts (every hex value lives here)
    widgets.py              DataTable, Console, SectionCard, LabeledEntry, StatusPill
    dialogs.py              confirm / preview / message modals
    wolf.py                 the wolf accent, drawn as vector polygons
    available_view.py       list + wrap form
    wrapped_view.py         tracked wrappers
    settings_view.py        paths and behaviour
tests/                      unit tests, fixtures, GUI smoke test
```

### Design notes

- **All CLI calls run on worker threads.** Tk is not thread-safe, so results come back through a
  queue drained on the main thread by `TaskBus`. Nothing touches a widget off the main thread.
- **Parsing is alias-tolerant.** The CLI owns its JSON schema, so `parser.py` accepts several
  spellings per field and degrades to partial data rather than raising.
  `tests/fixtures/list_all.json` is a real capture, so a schema change surfaces as a test failure
  instead of a silently blank table.
- **Every colour and font lives in `theme.py`.** No hex values in view code.
- **`config` is never used as an attribute name on the window.** `tkinter.Misc.config` *is*
  `Misc.configure`, so shadowing it breaks Tk internals; the settings object is `app.app_config`.

### Adding a view

1. Write `ui/your_view.py` with a `CTkFrame` subclass taking `(master, app)`.
2. Add a `("key", "Nav label")` entry to `NAV_ITEMS` in `ui/app.py`.
3. Return your view from `App._create_view`.
4. Optionally define `refresh()` (used by `Ctrl+R`) or `on_shown()` (called the first time the view
   becomes visible).

## Testing

```sh
python -m unittest discover -s tests -t .        # unit tests
python tests/smoke_gui.py                        # opens the real window for 6s
python tests/smoke_gui.py --view wrapped --select-first --shot shot.png
python tests/smoke_gui.py --base meta/muse-glimmer --preview
```

`smoke_gui.py` is not collected by unittest because it needs a desktop session. It builds the real
window, drives it through a timed sequence of `after` callbacks, and reports any unhandled exception
in a Tk callback as a failure — useful after touching layout code, which is hard to unit test.

## Known limits

- **A wrapper inherits its capability metadata from the base template, not from the wrapped model.**
  Context length, memory estimate, and the vision and tool-use flags are copied verbatim, so a
  wrapper can advertise more than the underlying model can actually do. A real example from this
  project: a text-only GGUF wrapped from a vision-capable template comes out with `vision: true`.
  This is inherent to how `lmstudio-caplift` works — borrowing a profile is the whole point — but it
  means you should check the template if a particular limit matters to you. Re-wrap with a better
  template if it is wrong.
- **No uninstall.** `lmstudio-caplift` has no remove command, so the UI does not pretend to have one.
  The Wrapped models view shows the target folder (with an *Open target folder* button) and the
  registry entry, which are the two things you delete by hand.
- **Long model keys are truncated in the table.** There is no horizontal scrollbar; the detail panel
  always shows the full value.
- **Windows only for now**, matching the CLI. `config.find_cli` and `wrapped_view._reveal` contain
  non-Windows branches that have not been exercised.
- **The executable is unsigned**, so SmartScreen warns on first run.
- **Model names in `tests/fixtures/` are real**, but personal paths have been replaced with
  `C:/Users/example/`.

## Credits

Built on **`lmstudio-caplift`** by **SegaraRai** — this project is an independent front end and
contains none of its source. All wrapping logic, template matching, and registry handling is the
CLI's; this UI only drives it and shows the results.

The wolf mark is drawn in `ui/wolf.py` as plain vector polygons — no image assets, nothing to bundle.

## License

[MIT](LICENSE) © 2026 michielza
