# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

Quick File Hasher is a single-file Python GTK4/libadwaita desktop app (`quick-file-hasher-app.py`) that computes file hashes. It doubles as a GNOME Nautilus extension. CI is configured via `.github/workflows/ci.yml`.

### Running the application

- **Headless (no GUI needed):** `xvfb-run .venv/bin/python quick-file-hasher-app.py [files...]`
- **With desktop display:** `DISPLAY=:1 .venv/bin/python quick-file-hasher-app.py [files...]`
- The app unconditionally imports `gi.require_version("Nautilus", "4.0")`, so the `gir1.2-nautilus-4.0` system package must be installed even for standalone (non-Nautilus) usage.
- Use `--help` to see CLI flags (`--algo`, `--recursive`, `--gitignore`, `--max-workers`, etc.).

### System dependencies (pre-installed by VM snapshot)

These apt packages are required and are installed in the VM snapshot — do not re-install in the update script:

`libgtk-4-dev libadwaita-1-dev gir1.2-gtk-4.0 gir1.2-adw-1 libgirepository1.0-dev libgirepository-2.0-dev libcairo2-dev gir1.2-nautilus-4.0 python3-nautilus python3-dev pkg-config xvfb`

### Python dependencies

Managed by `uv` (lockfile: `uv.lock`). Run `uv sync` from the workspace root.

### Key gotchas

- Building `pygobject` from source requires both `libgirepository1.0-dev` **and** `libgirepository-2.0-dev`. The latter provides the `girepository-2.0.pc` pkg-config file that the meson build needs.
- GTK4 apps emit `libEGL warning: DRI3 error` under Xvfb — this is harmless and can be ignored.
- `Gtk.Label` does **not** support a `monospace` constructor property in GTK4. Use the `monospace` CSS class instead.
- No automated test suite exists; manual GUI testing via `computerUse` subagent is the primary validation method. CI runs `py_compile` and `--help` smoke tests.
- The `Makefile` only handles install/uninstall to user-local directories; it has no build, test, or dependency targets.
