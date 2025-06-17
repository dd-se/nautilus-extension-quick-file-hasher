# Nautilus Compute Hash App

A modern Nautilus (GNOME Files) Python extension and standalone GTK4/libadwaita app to compute hashes for files and folders, with a beautiful UI and clipboard integration.

## Features

- **Nautilus context menu integration**: Right-click files/folders and select "Compute Hashes".
- **Modern GTK4/Adwaita UI**: Responsive, animated, and user-friendly interface.
- **Batch Processing**: Quickly compute hashes for multiple files and folders in parallel.
- **Copy/Compare**: Copy results to clipboard or compare file hash with clipboard contents.
- **Progress bar & cancel**: See progress and cancel long jobs.
- **Drag & Drop**: Drop files/folders into the app.


## Installation

1. **Copy the extension:**
   ```bash
   mkdir -p ~/.local/share/nautilus-python/extensions
   cp compute-hash-app.py ~/.local/share/nautilus-python/extensions/
   ```
2. **Restart Nautilus:**
   ```bash
   nautilus -q
   ```

## Usage

- **From Nautilus:**
  - Select files/folders, right-click, and select "Compute Hashes".
- **Standalone:**
  - Run directly: `python3 compute-hash-app.py [file1] [file2] [folder1] ...`
- **Drag-and-drop:**
  - Drag files/folders into the app window to compute their hashes.

## Screenshot

![demo](<demo.png>)

## Uninstall

Remove the extension:
```bash
rm ~/.local/share/nautilus-python/extensions/compute-hash-app.py
nautilus -q
```

## License
MIT

