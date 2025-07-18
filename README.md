# Nautilus Quick File Hasher Extension

A modern Nautilus (GNOME Files) Python extension and standalone GTK4/libadwaita app to compute hashes for files, with a beautiful UI and clipboard integration.

## Features

- **Nautilus context menu integration**: Right-click files/folders and select "Calculate Hashes".
- **Modern GTK4/libadwaita UI**: Responsive, animated, and user-friendly interface.
- **Batch Processing**: Quickly calculate hashes for multiple files and folders in parallel.
- **Copy/Compare**: Copy results to clipboard or compare file hash with clipboard contents.
- **Progress bar & cancel**: See progress and cancel long jobs.
- **Drag & Drop**: Drop files/folders into the app.

## Installation

1. **Install dependencies:**
  ```bash
  #Ubuntu
  sudo apt-get install python3-nautilus
  ```
   ```bash
  #Arch Linux
  sudo pacman -S nautilus-python
  ```
  ```bash
  #Fedora
  sudo dnf install nautilus-python
  ```
2. **Copy the extension manually:**
  ```bash
  mkdir -p ~/.local/share/nautilus-python/extensions
  cp quick-file-hasher-app.py ~/.local/share/nautilus-python/extensions/
  ```
3. **Or use the Makefile for easy install:**
  ```bash
  make install
  ```
4. **Restart Nautilus:**
  ```bash
  nautilus -q
  ```

## Usage

- **From Nautilus:**
  - Select files/folders, right-click, and select "Calculate Hashes".
- **From command-line:**
  - Run directly: `python3 quick-file-hasher-app.py [file1] [file2] [folder1] ...`
- **From overview:**
  - After running `make install`, a desktop shortcut will be created. You can then launch the app from your system application overview (press the Super key and search for "Quick File Hasher")
- **Drag-and-drop:**
  - Drag files/folders into the app window to compute their hashes.
- **Filter results:**
  - Just start typing to filter the results instantly. Press `ESC` to clear the search.

## Screenshot

![demo](<demo.png>)

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