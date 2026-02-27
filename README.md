<p align="center">
  <img src="resources/icon.svg" alt="Quick File Hasher Logo" width="128">
</p>
<h1 align="center">Quick File Hasher</h1>
<p align="center"><em>Verify your files with speed and confidence.</em></p>

Quick File Hasher is a modern Nautilus (GNOME Files) extension and standalone GTK4/libadwaita application for computing file hashes, featuring a polished UI and seamless clipboard integration.

## Features

- **Nautilus context menu integration**: Right-click files/folders and select "Quick File Hasher".
- **Modern GTK4/libadwaita UI**: Responsive, animated, and user-friendly interface.
- **Batch Processing**: Quickly calculate hashes for multiple files and folders in parallel.
- **Copy/Compare**: Copy results to clipboard or compare file hash with clipboard contents.
- **Progress bar & cancel**: See progress and cancel long jobs.
- **Drag & Drop**: Drop files/folders into the app.
- **Hash Text**: Hash arbitrary text strings with live preview — type or paste text, choose your algorithm and encoding, and see the hash update in real time (<kbd>Ctrl</kbd>+<kbd>T</kbd>).
- **Duplicate Detection**: Find files with identical hashes across your results and filter to show only duplicates (<kbd>Ctrl</kbd>+<kbd>D</kbd>).
- **Job Statistics**: See elapsed time, throughput (MB/s), and file count after each hashing job completes.
- **CSV Export**: Save results as CSV in addition to plain text for easy import into spreadsheets.

## Installation

### System Dependencies

The app requires GTK4, libadwaita, and Python GObject bindings. Install the system packages for your distribution:

```bash
# Ubuntu / Debian
sudo apt-get install python3-nautilus libgtk-4-dev libadwaita-1-dev \
  gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-nautilus-4.0 \
  libgirepository1.0-dev libgirepository-2.0-dev libcairo2-dev pkg-config
```
```bash
# Arch Linux
sudo pacman -S nautilus-python gtk4 libadwaita gobject-introspection cairo
```
```bash
# Fedora
sudo dnf install nautilus-python gtk4-devel libadwaita-devel \
  gobject-introspection-devel cairo-gobject-devel
```

### Python Dependencies

Install Python dependencies using [uv](https://github.com/astral-sh/uv):

```bash
uv sync
```

Or with pip:

```bash
pip install pycairo pygobject pygobject-stubs
```

### Application Install

1. **Copy the extension manually:**
   ```bash
   mkdir -p ~/.local/share/nautilus-python/extensions
   cp quick-file-hasher-app.py ~/.local/share/nautilus-python/extensions/
   ```
2. **Or use the Makefile for easy install:**
   ```bash
   make install
   ```
3. **Restart Nautilus:**
   ```bash
   nautilus -q
   ```

## Usage

- **From Nautilus:**
  - Select files/folders, right-click, and select "Quick File Hasher".
- **From command-line:**
  - Run directly: `python3 quick-file-hasher-app.py [file1] [file2] [folder1] ...`
- **From overview:**
  - After running `make install`, a desktop shortcut will be created. You can then launch the app from your system application overview. (Press the Super key and search for "Quick File Hasher")
- **Drag-and-drop:**
  - Drag files/folders into the app window to compute their hashes.
- **Filter results:**
  - Click the search icon in the header bar or press <kbd>Ctrl</kbd>+<kbd>F</kbd> to show the search bar. Filter results instantly as you type.
- **Multi-Hash:**
  - This feature enables selection of additional hashing algorithms for the given file.
- **Hash Text:**
  - Click "Hash Text" in the toolbar or press <kbd>Ctrl</kbd>+<kbd>T</kbd> to open the text hashing dialog. Type or paste text, select an algorithm and encoding (UTF-8, ASCII, Latin-1), and see the hash update live as you type.
- **Find Duplicates:**
  - Click "Duplicates" in the results toolbar or press <kbd>Ctrl</kbd>+<kbd>D</kbd> to identify and filter files with identical hashes.

## Arguments

You can also run the app with additional command-line arguments for more control:

```
python3 quick-file-hasher-app.py [file1] [file2] ... [folder] [--recursive] [--gitignore] [--max-workers 4] [--algo sha256]
```

Type `--help` for more information.

## Preferences

The **Preferences** dialog allows you to customize the application's behavior.
- **Recursive Traversal**
  - Enable this to process files within subdirectories.
- **Respect `.gitignore`**
  - When enabled, files and folders listed in the `.gitignore` file will be skipped.
- **Max Workers**
  - Sets the maximum number of parallel hashing operations. Adjust this value to optimize performance based on your systems capabilities.
- **Hashing Algorithm**
  - Select the default hashing algorithm from the list.
  - Available options include (hashlib): `md5`, `sha1`, `sha256`, `sha512`, `blake2b`, `blake2s` and more. The default is `sha256`.
- **Output Style**
  - Select the output format for checksum display.
  - Available options are the app's default style, sha256sum, and BSD.

#### **Note:** Changes to these settings are only saved across sessions when the `Persist` button is clicked. Additionally, command-line arguments can override these preferences at startup.

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| <kbd>Ctrl</kbd>+<kbd>O</kbd> | Open Files |
| <kbd>Ctrl</kbd>+<kbd>S</kbd> | Save Results |
| <kbd>Ctrl</kbd>+<kbd>T</kbd> | Hash Text |
| <kbd>Ctrl</kbd>+<kbd>F</kbd> | Show Search Bar |
| <kbd>Ctrl</kbd>+<kbd>D</kbd> | Find Duplicates |
| <kbd>Ctrl</kbd>+<kbd>R</kbd> | Toggle Sort |
| <kbd>Ctrl</kbd>+<kbd>L</kbd> | Clear Results |
| <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>C</kbd> | Copy All Results |
| <kbd>Ctrl</kbd>+<kbd>Q</kbd> | Quit |

## Screenshot

![demo](<resources/demo.png>)

## CI

This project uses GitHub Actions for continuous integration. On every pull request and push to `main`, the CI pipeline:

- Verifies syntax with `py_compile`
- Tests that the app loads correctly (`--help`, `--list-choices`)
- Runs a functional test that launches the app and hashes a file
- Tests against Python 3.12 and 3.13

## Uninstall

1. **Remove the extension manually**:
   ```bash
   rm ~/.local/share/nautilus-python/extensions/quick-file-hasher-app.py
   ```
2. **Or use the Makefile for easy uninstall:**
   ```bash
   make uninstall
   ```
3. **Restart Nautilus:**
   ```bash
   nautilus -q
   ```

## Tested Platforms

This extension has been tested on:

- Ubuntu 24.04 LTS
- Ubuntu 25.04
- Fedora 42
- CachyOS

## License

MIT
