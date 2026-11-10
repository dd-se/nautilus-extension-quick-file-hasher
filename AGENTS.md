# AGENTS.md

## Environment notes

### Project overview

Quick File Hasher is a single-file Python GTK4/libadwaita desktop app (`quick-file-hasher-app.py`) that computes file hashes. It doubles as a GNOME Nautilus extension. CI is configured via `.github/workflows/ci.yml`.

### Running the application

- **Headless (no GUI needed):** `xvfb-run .venv/bin/python quick-file-hasher-app.py [files...]`
- **With desktop display:** `DISPLAY=:1 .venv/bin/python quick-file-hasher-app.py [files...]`
- Nautilus GI bindings are required even for standalone use. The app supports typelib versions 4.0 and 4.1.

### System dependencies

These apt packages are required in the local environment and should be installed via the host package manager if missing:

`libgtk-4-dev libadwaita-1-dev gir1.2-gtk-4.0 gir1.2-adw-1 libgirepository1.0-dev libgirepository-2.0-dev libcairo2-dev python3-nautilus python3-dev pkg-config xvfb`

The Nautilus typelib package is `gir1.2-nautilus-4.0` on Ubuntu 24.04 and `gir1.2-nautilus-4.1` on Ubuntu 25.10/26.04.

### Python dependencies

Managed by `uv` (lockfile: `uv.lock`); run `uv sync` from the workspace root when dependencies need syncing.

### Key gotchas

- Building `pygobject` from source requires both `libgirepository1.0-dev` **and** `libgirepository-2.0-dev`. The latter provides the `girepository-2.0.pc` pkg-config file that the meson build needs.
- GTK4 apps emit `libEGL warning: DRI3 error` under Xvfb — this is harmless and can be ignored.
- `Gtk.Label` does **not** support a `monospace` constructor property in GTK4. Use the `monospace` CSS class instead.
- CI runs syntax and launch smoke checks (`py_compile`, `--help`, and `--list-choices`).
- The `Makefile` provides install, uninstall, and symlink targets; it has no test target.
