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

1. **Copy the extension:**
   ```bash
   mkdir -p ~/.local/share/nautilus-python/extensions
   cp quick-file-hasher-app.py ~/.local/share/nautilus-python/extensions/
   ```
2. **Restart Nautilus:**
   ```bash
   nautilus -q
   ```

## Usage

- **From Nautilus:**
  - Select files/folders, right-click, and select "Calculate Hashes".
- **From command-line:**
  - Run directly: `python3 quick-file-hasher-app.py [file1] [file2] [folder1] ...`
- **Drag-and-drop:**
  - Drag files/folders into the app window to compute their hashes.

## Screenshot

![demo](<demo.png>)

## Uninstall

Remove the extension:
```bash
rm ~/.local/share/nautilus-python/extensions/quick-file-hasher-app.py
nautilus -q
```

## License
MIT

