#!/usr/bin/env python3

# MIT License

# Copyright (c) 2025 Doğukan Doğru

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import hashlib
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
import warnings
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import lru_cache
from itertools import repeat
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Literal

signal.signal(signal.SIGINT, lambda s, f: exit(print("Interrupted by user (Ctrl+C)")))
os.environ["LANG"] = "en_US.UTF-8"
import gi  # type: ignore

gi.require_version(namespace="Gtk", version="4.0")
gi.require_version(namespace="Adw", version="1")
gi.require_version(namespace="Nautilus", version="4.0")

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Nautilus, Pango  # type: ignore

APP_ID = "com.github.dd-se.quick-file-hasher"
APP_VERSION = "1.9.1"

DEFAULTS = {
    "algo": "sha256",
    "max-workers": 4,
    "recursive": False,
    "gitignore": False,
    "ignore-empty-files": False,
    "save-errors": False,
    "relative-paths": False,
    "include-time": True,
    "output-style": 0,
}
PRIORITY_ALGORITHMS = ["md5", "sha1", "sha256", "sha512"]
AVAILABLE_ALGORITHMS = PRIORITY_ALGORITHMS + sorted(hashlib.algorithms_available - set(PRIORITY_ALGORITHMS))
MAX_WIDTH = max(len(algo) for algo in AVAILABLE_ALGORITHMS)
NAUTILUS_CONTEXT_MENU_ALGORITHMS = [None] + AVAILABLE_ALGORITHMS
CONFIG_DIR = Path(GLib.get_user_config_dir()) / APP_ID
CONFIG_FILE = CONFIG_DIR / "config.json"
CHECKSUM_FORMATS: list[dict[str, str]] = [
    {
        "name": "Default",
        "description": "Uses the application's default checksum output format",
        "style": "{filename}:{hash}:{algo}",
    },
    {
        "name": "sha256sum",
        "description": "GNU coreutils style: '<hash>  <filename>'",
        "style": "{hash}  {filename}",
    },
    {
        "name": "BSD-style",
        "description": "BSD style: '<algorithm> (<filename>) = <hash>'",
        "style": "{algo} ({filename}) = {hash}",
    },
]
CSS = b"""
toast {
    background-color: #000000;
}
.view-switcher button {
    background-color: #404040;
    color: white;
    transition: background-color 0.3s ease;
}
.view-switcher button:nth-child(1):hover {
    background-color: #3074cf;
}
.view-switcher button:nth-child(1):checked {
    background-color: #3074cf;
}
.view-switcher button:nth-child(2):hover {
    background-color: #c7162b;
}
.view-switcher button:nth-child(2):checked {
    background-color: #c7162b;
}
.no-background {
    background-color: @theme_bg_color;
}
.search-bg-color {
    background-color: shade(@theme_bg_color, 0.8);
}
.custom-style-row {
    background-color: #3D3D3D;
    border-radius: 6px;
    padding-top: 8px;
    padding-left : 8px;
    padding-right : 8px;
    padding-bottom: 8px;
}
/*
.custom-style-row:hover {
    background-color: #454545;
}
*/
.darker-action-row {
    background-color: rgba(0, 0, 0, 0.2);
}
.drag-overlay {
    background-color: alpha(@accent_bg_color, 0.5);
    color: @accent_fg_color;
}
.custom-success {
    color: #57EB72;
}
.custom-error {
    color: #FF938C;
}
.custom-toggle-btn:checked {
    background: shade(@theme_selected_bg_color,0.9);
}
"""

css_provider = Gtk.CssProvider()
css_provider.load_from_data(CSS)
Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def get_logger(name: str) -> logging.Logger:
    loglevel_str = os.getenv("LOGLEVEL", "INFO").upper()
    # warnings.filterwarnings("ignore" if loglevel_str == "INFO" else "default", category=DeprecationWarning)
    loglevel = getattr(logging, loglevel_str, logging.INFO)
    logger = logging.getLogger(name)
    logger.setLevel(loglevel)
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] %(levelname)-6s | %(name)-15s | %(funcName)-21s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


Adw.init()
Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)


class AdwNautilusExtension(GObject.GObject, Nautilus.MenuProvider):
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)

    def nautilus_launch_app(
        self,
        menu_item: Nautilus.MenuItem,
        files: list[str],
        hash_algorithm: str | None = None,
        recursive_mode: bool = False,
    ) -> None:
        self.logger.debug(f"App '{APP_ID}' launched by file manager")

        cmd = ["python3", __file__] + files
        if hash_algorithm:
            cmd.extend(["--algo", hash_algorithm])

        if recursive_mode:
            cmd.extend(["--recursive", "--gitignore"])

        self.logger.debug(f"Args: '{cmd[2:]}'")
        subprocess.Popen(cmd)

    def create_menu(self, files: list[str], caller: int, has_dir: bool, PREFIX: str = "QuickFileHasher_OpenInApp") -> list[Nautilus.MenuItem]:
        quick_file_hasher_menu = Nautilus.MenuItem(
            name=f"{PREFIX}_Menu_{caller}",
            label="Quick File Hasher",  # Quick
        )
        quick_file_hasher_submenu = Nautilus.Menu()  # >
        quick_file_hasher_menu.set_submenu(quick_file_hasher_submenu)  # Quick >

        if has_dir:
            simple_menu = Nautilus.MenuItem(
                name=f"{PREFIX}_Simple_{caller}",  # Simple Menu
                label="Simple",
            )

            quick_file_hasher_submenu.append_item(simple_menu)  # Quick > Simple
            simple_submenu = Nautilus.Menu()  # >
            simple_menu.set_submenu(simple_submenu)  # Quick > Simple >

            recursive_menu = Nautilus.MenuItem(
                name=f"{PREFIX}_Recursive_{caller}",  # Recursive Menu
                label="Recursive",
            )

            quick_file_hasher_submenu.append_item(recursive_menu)  # Quick > Recursive
            recursive_submenu = Nautilus.Menu()  # >
            recursive_menu.set_submenu(recursive_submenu)  # Quick > Recursive >

            for hash_name in NAUTILUS_CONTEXT_MENU_ALGORITHMS:
                label = hash_name.replace("_", "-").upper() if hash_name else "DEFAULT"
                item_hash_simple = Nautilus.MenuItem(
                    name=f"{PREFIX}_{label}_Simple_{caller}",  # MD5 Simple
                    label=label,
                )
                item_hash_simple.connect("activate", self.nautilus_launch_app, files, hash_name, False)

                simple_submenu.append_item(item_hash_simple)  # Quick > Simple > MD5

                item_hash_recursive = Nautilus.MenuItem(
                    name=f"{PREFIX}_{label}_Recursive_{caller}",  # MD5 Recursive
                    label=label,
                )
                item_hash_recursive.connect("activate", self.nautilus_launch_app, files, hash_name, True)

                recursive_submenu.append_item(item_hash_recursive)  # Quick > Recursive > MD5

        else:
            for hash_name in NAUTILUS_CONTEXT_MENU_ALGORITHMS:
                label = hash_name.replace("_", "-").upper() if hash_name else "DEFAULT"
                item = Nautilus.MenuItem(
                    name=f"{PREFIX}_{label}_{caller}",  # MD5
                    label=label,
                )
                item.connect("activate", self.nautilus_launch_app, files, hash_name)
                quick_file_hasher_submenu.append_item(item)  #  Quick > MD5

        return [quick_file_hasher_menu]

    def validate_to_string(self, files: list[Nautilus.FileInfo]) -> tuple[bool, list[str]]:
        has_dir = False
        validated_files = []
        for obj in files:
            if obj.is_directory():
                has_dir = True
            if file := obj.get_location().get_path():
                validated_files.append(file)
        return has_dir, validated_files

    def get_background_items(self, current_folder: Nautilus.FileInfo) -> list[Nautilus.MenuItem]:
        if not current_folder.is_directory():
            return []
        return self.create_menu([current_folder.get_location().get_path()], 1, True)

    def get_file_items(self, files: list[Nautilus.FileInfo]) -> list[Nautilus.MenuItem]:
        has_dir, files = self.validate_to_string(files)
        if not files:
            return []
        return self.create_menu(files, 2, has_dir)


class ConfigMixin:
    def init_config(self) -> None:
        self.cm_logger = get_logger("ConfigMixin")
        self._load_config_file()

    def _get_config_file(self) -> dict | None:
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config: dict = json.load(f)
                return config

        except json.JSONDecodeError as e:
            self.cm_logger.error(f"'{CONFIG_FILE}': {e}. Using defaults.")

        except Exception as e:
            self.cm_logger.error(f"'{CONFIG_FILE}': {e}. Using defaults.")

    def _load_config_file(self) -> None:
        self._persisted_config = DEFAULTS.copy()

        if loaded_config := self._get_config_file():
            self._persisted_config.update(loaded_config)
            self.cm_logger.debug(f"Loaded config from '{CONFIG_FILE}'")

        self._working_config = self._persisted_config.copy()

    def persist_working_config_to_file(self) -> bool | None:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._working_config, f, indent=4, sort_keys=True)
                self._persisted_config = self._working_config.copy()

            self.cm_logger.debug(f"Preferences saved to file: '{CONFIG_FILE}'")
            return True
        except Exception as e:
            self.cm_logger.error(f"Error saving preferences to '{CONFIG_FILE}': {e}")

    def update(self, config_key: str, new_value) -> bool | None:
        if self.get(config_key) != new_value:
            self._working_config[config_key] = new_value
            self.cm_logger.debug(f"Configuration for '{config_key}' changed to '{new_value}'")
            return True

    def get(self, config_key: str, default=None):
        return self._working_config.get(config_key, default)

    def get_persisted_config(self) -> dict:
        return self._persisted_config.copy()

    def get_working_config(self) -> dict:
        return self._working_config.copy()


class Preferences(Adw.PreferencesWindow, ConfigMixin):
    __gtype_name__ = "Preferences"
    _instance = None
    __gsignals__ = {
        "call-application": (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
        "call-main-window": (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT,)),
    }

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, **kwargs):
        if hasattr(self, "_initialized"):
            return
        super().__init__(title="Preferences", modal=True, hide_on_close=True, **kwargs)
        self.init_config()
        self.set_size_request(0, MainWindow.DEFAULT_HEIGHT - 100)
        self.logger = get_logger(self.__class__.__name__)
        self._setting_widgets: dict[str, Adw.ActionRow | list[Gtk.ToggleButton]] = {}

        self._setup_processing_page()
        self._setup_saving_page()
        self._setup_hashing_page()

        self.apply_config_ui(self.get_working_config())
        self._initialized = True

    def _setup_processing_page(self) -> None:
        processing_page = Adw.PreferencesPage(
            title="Processing",
            icon_name="edit-find-symbolic",
        )
        self.add(processing_page)

        processing_group = Adw.PreferencesGroup(
            description="Configure how files and folders are processed",
        )
        processing_page.add(group=processing_group)

        self.setting_recursive = self._create_switch_row("recursive", "edit-find-symbolic", "Recursive Traversal", "Enable to process all files in subdirectories")
        processing_group.add(child=self.setting_recursive)

        self.setting_gitignore = self._create_switch_row("gitignore", "action-unavailable-symbolic", "Respect .gitignore", "Skip files and folders listed in .gitignore file")
        processing_group.add(child=self.setting_gitignore)

        self.setting_ignore_empty_files = self._create_switch_row("ignore-empty-files", "action-unavailable-symbolic", "Ignore Empty Files", "Don't raise errors for empty files")
        processing_group.add(child=self.setting_ignore_empty_files)

        processing_group.add(self._create_buttons())

    def _setup_saving_page(self) -> None:
        saving_page = Adw.PreferencesPage(title="Saving", icon_name="document-save-symbolic")
        self.add(saving_page)

        saving_group = Adw.PreferencesGroup(description="Configure how results are saved")
        saving_page.add(group=saving_group)

        self.setting_save_errors = self._create_switch_row("save-errors", "dialog-error-symbolic", "Save Errors", "Save errors to results file or clipboard")
        saving_group.add(child=self.setting_save_errors)

        self.setting_include_time = self._create_switch_row("include-time", "edit-find-symbolic", "Include Timestamp", "Include timestamp in results")
        saving_group.add(child=self.setting_include_time)

        self.setting_relative_path = self._create_switch_row(
            "relative-paths",
            "view-list-symbolic",
            "Relative Paths",
            "Display results using paths relative to the current working directory",
        )
        self.setting_relative_path.connect("notify::active", lambda *_: self._set_example_format_text(self.get_format_style()))
        saving_group.add(child=self.setting_relative_path)

        self._create_checksum_format_toggle_group(saving_page)

    def _setup_hashing_page(self) -> None:
        hashing_page = Adw.PreferencesPage(title="Hashing", icon_name="dialog-password-symbolic")
        self.add(hashing_page)

        hashing_group = Adw.PreferencesGroup(description="Configure hashing behavior")
        hashing_page.add(group=hashing_group)

        self.setting_algorithm = Adw.ComboRow(
            name="algo",
            title="Hash Algorithm",
            subtitle="Select the default hashing algorithm for new jobs",
            model=Gtk.StringList.new(AVAILABLE_ALGORITHMS),
            valign=Gtk.Align.CENTER,
        )

        self.setting_algorithm.add_prefix(Gtk.Image.new_from_icon_name("dialog-password-symbolic"))
        self.setting_algorithm.connect("notify::selected", self._on_algo_selected)
        self._add_reset_button(self.setting_algorithm)
        self._setting_widgets[self.setting_algorithm.get_name()] = self.setting_algorithm

        hashing_group.add(child=self.setting_algorithm)

        self.setting_max_workers = Adw.SpinRow(
            name="max-workers",
            title="Max Workers",
            subtitle="Set how many files are hashed in parallel",
            adjustment=Gtk.Adjustment.new(4, 1, 16, 1, 5, 0),
            climb_rate=1,
            digits=0,
            editable=True,
            numeric=True,
        )
        self.setting_max_workers.add_prefix(Gtk.Image.new_from_icon_name("process-working-symbolic"))
        self.setting_max_workers.connect("notify::value", self._on_spin_row_changed)
        self._add_reset_button(self.setting_max_workers)
        self._setting_widgets[self.setting_max_workers.get_name()] = self.setting_max_workers
        hashing_group.add(child=self.setting_max_workers)

        hashing_group.add(child=self._create_buttons())

    def _create_switch_row(self, name: str, icon_name: str, title: str, subtitle: str) -> Adw.SwitchRow:
        switch_row = Adw.SwitchRow(name=name, title=title, subtitle=subtitle)
        switch_row.add_prefix(Gtk.Image.new_from_icon_name(icon_name))
        switch_row.connect("notify::active", self._on_switch_row_changed)
        self._add_reset_button(switch_row)
        self._setting_widgets[name] = switch_row
        return switch_row

    def _create_checksum_format_toggle_group(self, page: Adw.PreferencesPage) -> None:
        name = "output-style"
        self.format_style = ""

        group = Adw.PreferencesGroup()
        toggle_container = Gtk.Box(valign=Gtk.Align.CENTER, css_classes=["linked"])
        self.checksum_format_example_text = Adw.ActionRow(css_classes=["monospace", "darker-action-row"], title_lines=1)
        self.checksum_format_example_text.add_prefix(Gtk.Box(hexpand=True))
        self.setting_checksum_format_toggle_group: list[Gtk.ToggleButton] = []
        self._setting_widgets[name] = self.setting_checksum_format_toggle_group

        first_toggle = None
        for fmt in CHECKSUM_FORMATS:
            toggle = Gtk.ToggleButton(name=name, label=fmt["name"], tooltip_text=fmt["description"], css_classes=["custom-toggle-btn"])
            toggle.connect("toggled", self._on_format_selected, fmt["style"])

            if first_toggle is None:
                first_toggle = toggle
            else:
                toggle.set_group(first_toggle)

            toggle_container.append(toggle)
            self.setting_checksum_format_toggle_group.append(toggle)

        output_format_picker = Adw.ActionRow(name=name, title="Output Format", tooltip_text="Choose checksum output format", title_lines=1)
        output_format_picker.add_prefix(Gtk.Image.new_from_icon_name("text-x-generic-symbolic"))
        output_format_picker.add_suffix(toggle_container)

        group.add(output_format_picker)
        group.add(self.checksum_format_example_text)
        group.add(self._create_buttons())

        page.add(group)

    def _get_reset_button(self) -> Gtk.Button:
        reset_button = Gtk.Button(
            label="Reset",
            css_classes=["flat"],
            valign=Gtk.Align.CENTER,
            tooltip_markup="<b>Reset</b> to default value",
            icon_name="edit-undo-symbolic",
        )
        return reset_button

    def _add_reset_button(self, row: Adw.ActionRow) -> None:
        reset_button = self._get_reset_button()
        value = DEFAULTS[row.get_name()]
        if isinstance(row, Adw.SwitchRow):
            reset_button.connect("clicked", lambda _: row.set_active(value))

        elif isinstance(row, Adw.SpinRow):
            reset_button.connect("clicked", lambda _: row.set_value(value))

        elif isinstance(row, Adw.ComboRow):
            reset_button.connect("clicked", lambda _: row.set_selected(AVAILABLE_ALGORITHMS.index(value)))

        row.add_suffix(reset_button)

    def _create_buttons(self) -> Gtk.Box:
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        main_box.append(spacer)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        button_box.set_margin_top(20)
        main_box.append(button_box)

        button_save_preferences = Gtk.Button(
            label="Persist",
            tooltip_text="Persist current preferences to config file",
            hexpand=True,
        )
        button_save_preferences.connect("clicked", lambda _: self._persist_preferences())
        button_box.append(button_save_preferences)

        button_reset_preferences = Gtk.Button(
            label="Reset",
            tooltip_text="Reset all preferences to default values",
            hexpand=True,
        )
        button_reset_preferences.add_css_class("destructive-action")
        button_reset_preferences.connect("clicked", lambda _: self._reset_preferences())
        button_box.append(button_reset_preferences)
        return main_box

    def get_format_style(self) -> str:
        return self.format_style

    def get_algorithm(self) -> str:
        return self.get("algo")

    def use_relative_paths(self) -> bool:
        return self.get("relative-paths")

    def save_errors(self) -> bool:
        return self.get("save-errors")

    def include_time(self) -> bool:
        return self.get("include-time")

    def send_toast(self, msg: str, timeout: int = 1) -> None:
        self.add_toast(Adw.Toast(title=msg, timeout=timeout))

    def apply_config_ui(self, config: dict) -> None:
        self.logger.debug("Applying config to UI components")
        for key, value in config.items():
            if widget := self._setting_widgets.get(key):
                if isinstance(widget, Adw.SwitchRow):
                    widget.set_active(value)

                elif isinstance(widget, Adw.SpinRow):
                    widget.set_value(value)

                elif isinstance(widget, Adw.ComboRow):
                    widget.set_selected(AVAILABLE_ALGORITHMS.index(value))

                elif isinstance(widget, list):
                    if 0 <= value < len(widget):
                        toggle: Gtk.ToggleButton = widget[value]
                        toggle.set_active(True)
        return True

    def _persist_preferences(self) -> None:
        success = self.persist_working_config_to_file()
        if success:
            self.send_toast("Success")
        else:
            self.send_toast("Something went wrong!")

    def _reset_preferences(self):
        success = self.apply_config_ui(DEFAULTS)
        if success:
            self.send_toast("Reset")
        else:
            self.send_toast("Something went wrong!")

    def _set_example_format_text(self, format_style: str) -> None:
        example_file = "example.txt" if self.use_relative_paths() else "/folder/example.txt"
        example_hash = "fdfba9fc68f1f150a4"
        example_algo = "SHA256"

        example_text = format_style.format(hash=example_hash, filename=example_file, algo=example_algo)
        self.checksum_format_example_text.set_title(example_text)

    def _on_format_selected(self, button: Gtk.ToggleButton, format_style: str) -> None:
        self.format_style = format_style
        self._set_example_format_text(self.format_style)

        button_index = self.setting_checksum_format_toggle_group.index(button)
        config_key = button.get_name()
        self.update(config_key, button_index)

    def _on_switch_row_changed(self, switch_row: Adw.SwitchRow, param: GObject.ParamSpec) -> None:
        new_value = switch_row.get_active()
        config_key = switch_row.get_name()
        success = self.update(config_key, new_value)
        if success:
            if config_key == "save-errors":
                self.emit("call-main-window", ["trigger-on-items-changed"])

            elif config_key == "relative-paths":
                self.emit("call-main-window", ["trigger-path-update", new_value])

    def _on_spin_row_changed(self, spin_row: Adw.SpinRow, param: GObject.ParamSpec) -> None:
        new_value = int(spin_row.get_value())
        config_key = spin_row.get_name()
        self.update(config_key, new_value)

    def _on_algo_selected(self, algo: Adw.ComboRow, param: GObject.ParamSpec) -> None:
        selected_hashing_algorithm = algo.get_selected_item().get_string()
        config_key = algo.get_name()
        self.update(config_key, selected_hashing_algorithm)


class IgnoreRule:
    def __init__(self, pattern: str, base_path: Path):
        self.negation = pattern.startswith("!")
        if self.negation:
            pattern = pattern[1:]

        self.directory_only = pattern.endswith("/")
        pattern = pattern.rstrip("/")

        self.anchored = pattern.startswith("/")
        if self.anchored:
            pattern = pattern[1:]

        if pattern.startswith("\\") and len(pattern) > 1 and pattern[1] in ("#", "!"):
            pattern = pattern[1:]

        pattern = self._clean_trailing_spaces(pattern)
        pattern = pattern.replace("\\ ", " ")

        self.regex = re.compile(self._to_regex(pattern))
        self.base_path = base_path

    def _clean_trailing_spaces(self, pattern: str) -> str:
        while pattern.endswith(" ") and not pattern.endswith("\\ "):
            pattern = pattern[:-1]
        return pattern

    def _to_regex(self, pattern: str) -> str:
        def handle_char_class(p: str) -> str:
            if p.startswith("[!"):
                return "[^" + re.escape(p[2:-1]) + "]"
            return p

        parts = []
        i = 0
        while i < len(pattern):
            if pattern[i] == "[" and i + 1 < len(pattern):
                j = pattern.find("]", i)
                if j == -1:
                    parts.append(re.escape(pattern[i:]))
                    break
                parts.append(handle_char_class(pattern[i : j + 1]))
                i = j + 1
            else:
                parts.append(re.escape(pattern[i]))
                i += 1

        pattern = "".join(parts)
        pattern = pattern.replace(r"\*\*", ".*")
        pattern = pattern.replace(r"\*", "[^/]*")
        pattern = pattern.replace(r"\?", "[^/]")

        prefix = r"^" if self.anchored else r"(^|/)"
        suffix = r"(/|$)" if self.directory_only else r"($|/)"

        return f"{prefix}{pattern}{suffix}"

    @lru_cache(maxsize=None)
    def _get_rel_path(self, path: Path) -> str:
        return path.relative_to(self.base_path).as_posix()

    def match(self, path: Path) -> bool:
        if self.directory_only and path.is_file():
            return False

        rel_path = self._get_rel_path(path)
        return bool(self.regex.search(rel_path))

    @staticmethod
    def parse_gitignore(gitignore_path: Path, extend: list["IgnoreRule"] | None = None) -> list["IgnoreRule"]:
        rules = extend or [IgnoreRule(".git/", gitignore_path.parent)]

        with gitignore_path.open() as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    rules.append(IgnoreRule(line, gitignore_path.parent))
        return rules

    @staticmethod
    def is_ignored(path: Path, rules: list["IgnoreRule"]) -> bool:
        for rule in reversed(rules):
            if rule.match(path):
                return not rule.negation
            elif rule.directory_only:
                if any(rule.match(parent) for parent in path.parents if parent.is_relative_to(rule.base_path)):
                    return not rule.negation
        return False


class QueueUpdateHandler:
    def __init__(self):
        self.q = Queue()
        self.c = 0

    def update_progress(self, progress: float) -> None:
        self.c = self.c + 1
        if self.c == 5 or progress == 1.0:
            self.c = 0
            self.q.put(("progress", progress))

    def update_result(self, base_path: Path, file: Path, hash_value: str, algo: str) -> None:
        self.q.put(("result", base_path, file, hash_value, algo))

    def update_error(self, file: Path, error: str) -> None:
        self.q.put(("error", file, error))

    def update_toast(self, message: str) -> None:
        self.q.put(("toast", message))

    def get_update(self):
        return self.q.get_nowait()

    def is_empty(self) -> bool:
        return self.q.empty()

    def reset(self) -> None:
        self.q = Queue()


class CalculateHashes:
    def __init__(self, queue: QueueUpdateHandler, event: threading.Event):
        self.logger = get_logger(self.__class__.__name__)
        self.queue_handler = queue
        self.cancel_event = event
        self._total_bytes = 0
        self._total_bytes_read = 0

    def __call__(self, base_paths: Iterable[Path], paths: Iterable[Path], hash_algorithms: Iterable[str], options: dict) -> None:
        jobs = self._create_jobs(base_paths, paths, options)
        self._execute_jobs(jobs, hash_algorithms, options)

    def _execute_jobs(self, jobs: dict[str, list], hash_algorithms: Iterable[str], options: dict) -> None:
        max_workers = options.get("max-workers")
        with ThreadPoolExecutor(max_workers) as executor:
            self.logger.debug(f"Starting hashing with {max_workers} workers")
            list(executor.map(self._hash_task, jobs["base_paths"], jobs["paths"], hash_algorithms, jobs["sizes"]))

    def _create_jobs(self, base_paths: Iterable[Path], paths: Iterable[Path], options: dict) -> dict[str, list]:
        jobs = {"base_paths": [], "paths": [], "sizes": []}

        for base_path, path in zip(base_paths, paths):
            try:
                if not path.exists():
                    self.queue_handler.update_error(path, "File or directory not found.")
                    continue

                ignore_rules = []

                if path.is_dir():
                    if options.get("gitignore"):
                        gitignore_file = path / ".gitignore"

                        if gitignore_file.exists():
                            ignore_rules = IgnoreRule.parse_gitignore(gitignore_file)
                            self.logger.debug(f"Added rules early: {gitignore_file} ({len(ignore_rules)})")

                    for sub_path in path.iterdir():
                        if IgnoreRule.is_ignored(sub_path, ignore_rules):
                            self.logger.debug(f"Skipped early: {sub_path}")
                            continue
                        self._process_path_n_rules(base_path, sub_path, ignore_rules, jobs, options)

                elif path.is_file():
                    self._process_path_n_rules(base_path, path, ignore_rules, jobs, options)

            except Exception as e:
                self.logger.debug(f"Error processing {path.name}: {e}")
                self.queue_handler.update_error(path, str(e))

        if self._total_bytes == 0:
            self.queue_handler.update_progress(1)
            self.queue_handler.update_toast("❌ Zero bytes. No files were hashed.")

        return jobs

    def _process_path_n_rules(self, base_path: Path, current_path: Path, current_rules: list[IgnoreRule], jobs: dict[str, list], options: dict) -> None:
        if self.cancel_event.is_set():
            return
        try:
            if current_path.is_symlink():
                self.queue_handler.update_error(current_path, "Symbolic links are not supported")
                self.logger.debug(f"Skipped symbolic link: {current_path}")

            elif IgnoreRule.is_ignored(current_path, current_rules):
                self.logger.debug(f"Skipped late: {current_path}")

            elif current_path.is_file():
                file_size = current_path.stat().st_size

                if file_size == 0:
                    if not options.get("ignore-empty-files"):
                        self.queue_handler.update_error(current_path, "File is empty")

                else:
                    self._add_file_size(file_size)
                    jobs["base_paths"].append(base_path)
                    jobs["paths"].append(current_path)
                    jobs["sizes"].append(file_size)

            elif current_path.is_dir() and options.get("recursive"):
                local_rules = []

                if options.get("gitignore"):
                    local_rules = current_rules.copy()
                    gitignore_file = current_path / ".gitignore"

                    if gitignore_file.exists():
                        IgnoreRule.parse_gitignore(gitignore_file, extend=local_rules)
                        self.logger.debug(f"Added rule late: {gitignore_file} ({len(local_rules)})")

                for sub_path in current_path.iterdir():
                    self._process_path_n_rules(base_path, sub_path, local_rules, jobs, options)

            else:
                current_path.stat()

        except Exception as e:
            self.logger.debug(f"Error processing {current_path.name}: {e}")
            self.queue_handler.update_error(current_path, str(e))

    @property
    def _current_progress(self) -> float:
        return min(self._total_bytes_read / self._total_bytes, 1.0)

    def _hash_task(self, base_path: Path, file: Path, algorithm: str, file_size: int, shake_length: int = 32) -> None:
        if self.cancel_event.is_set():
            return
        try:
            if file_size > 1024 * 1024 * 100:
                chunk_size = 1024 * 1024 * 4

            else:
                chunk_size = 1024 * 1024

            hash_task_bytes_read = 0
            hash_obj = hashlib.new(algorithm)
            with open(file, "rb") as f:
                while chunk := f.read(chunk_size):
                    if self.cancel_event.is_set():
                        return

                    hash_obj.update(chunk)
                    bytes_read = len(chunk)
                    self._total_bytes_read += bytes_read
                    hash_task_bytes_read += bytes_read
                    self.queue_handler.update_progress(self._current_progress)

            hash_value = hash_obj.hexdigest(shake_length) if "shake" in algorithm else hash_obj.hexdigest()
            self.queue_handler.update_result(base_path, file, hash_value, algorithm)

        except Exception as e:
            self._total_bytes_read += file_size - hash_task_bytes_read

            if self._total_bytes > 0:
                self.queue_handler.update_progress(self._current_progress)

            self.queue_handler.update_error(file, str(e))
            self.logger.exception(f"Error processing {file.name}: {e}", stack_info=True)

    def _add_file_size(self, bytes_: int) -> None:
        self._total_bytes += bytes_

    def reset_counters(self) -> None:
        self._total_bytes_read = 0
        self._total_bytes = 0


class ResultRowData(GObject.Object):
    __gtype_name__ = "ResultRowData"

    hash_value = GObject.Property(type=str)
    algo = GObject.Property(type=str)

    def __init__(self, base_path: Path, path: Path, hash_value: str, algo: str, relative_path: bool = False, **kwargs):
        super().__init__(hash_value=hash_value, algo=algo, **kwargs)
        self.base_path = base_path
        self.path = path
        self.relative_path = relative_path

    def __call__(self, format_style: str) -> str:
        return format_style.format(hash=self.hash_value, filename=self.path_display, algo=self.algo)

    @GObject.Property(type=str)
    def path_display(self) -> str:
        if self.relative_path:
            return GLib.markup_escape_text((self.base_path.name / self.path.relative_to(self.base_path)).as_posix())
        return GLib.markup_escape_text(self.path.as_posix())

    @GObject.Property(type=bool, default=False)
    def relative_path(self) -> bool:
        return self._relative_path

    @relative_path.setter
    def relative_path(self, state: bool) -> None:
        self._relative_path = state
        self.notify("path_display")

    def get_search_fields(self) -> tuple[str, str, str]:
        return (self.path.as_posix().lower(), self.hash_value, self.algo)

    def signal_handler(self, emitter: Any, args: list) -> None:
        args_copy = args.copy()
        action = args_copy.pop(0)
        if action == "trigger-path-update":
            use_relative_path = args_copy.pop(0)
            self.relative_path = use_relative_path


class ErrorRowData(GObject.Object):
    __gtype_name__ = "ErrorRowData"

    def __init__(self, path: Path, error_message: str, **kwargs):
        super().__init__(**kwargs)
        self.path = path
        self.error_message = error_message

    @property
    def path(self) -> str:
        return GLib.markup_escape_text(self._path.as_posix())

    @path.setter
    def path(self, path: Path) -> None:
        self._path = path

    @property
    def error_message(self) -> str:
        return GLib.markup_escape_text(self._error_message)

    @error_message.setter
    def error_message(self, error_message: str) -> None:
        self._error_message = error_message

    def get_search_fields(self) -> tuple[str, str, str]:
        return (self._path.as_posix().lower(), self.error_message)

    def __str__(self) -> str:
        return f"{self.path}:ERROR:{self.error_message}"


class HashRow(Gtk.Box):
    __gtype_name__ = "HashRow"
    base_path: Path
    path: Path
    button_delete: Gtk.Button
    noop_copy = False
    noop_cmp = False

    def __init__(self, **kwargs):
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            css_classes=["custom-style-row"],
            spacing=12,
            **kwargs,
        )
        self.prefix_icon = Gtk.Image(margin_start=4)
        self.prefix_label = Gtk.Label(width_chars=MAX_WIDTH)
        self.prefix_label.add_css_class("dim-label")
        self.append(self.prefix_icon)
        self.append(self.prefix_label)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        self.append(content_box)

        self.title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE)
        self.subtitle = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, css_classes=["dim-label", "caption"], margin_top=2)
        content_box.append(self.title)
        content_box.append(self.subtitle)

        self.suffix_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, valign=Gtk.Align.CENTER)
        self.append(self.suffix_box)

    def _create_button(self, icon_name: str | None, tooltip_text: str, callback: Callable, *args) -> Gtk.Button:
        if icon_name is None:
            button = Gtk.Button()
        else:
            button = Gtk.Button.new_from_icon_name(icon_name)

        if callback:
            button.connect("clicked", callback, *args)

        button.set_valign(Gtk.Align.CENTER)
        button.set_tooltip_text(tooltip_text)
        self.suffix_box.append(button)
        return button

    def _on_click_delete(self, button: Gtk.Button, list_item: Gtk.ListItem, model: Gio.ListStore) -> None:
        button.set_sensitive(False)
        row_data = list_item.get_item()

        found, position = model.find(row_data)
        if not found:
            raise ValueError("Item not found in original model")

        anim = Adw.TimedAnimation(
            widget=self,
            value_from=1.0,
            value_to=0.3,
            duration=100,
            target=Adw.CallbackAnimationTarget.new(lambda opacity: self.set_opacity(opacity)),
        )
        anim.connect("done", lambda _: model.remove(position))
        anim.play()

    def _on_click_copy(self, button: Gtk.Button, css: str | None = None) -> None:
        if self.noop_copy:
            return
        self.noop_copy = True
        button.get_clipboard().set(self.subtitle.get_text())
        icon_name = button.get_icon_name()
        button.set_icon_name("object-select-symbolic")

        if css:
            button.add_css_class(css)

        def reset():
            button.set_icon_name(icon_name)
            button.remove_css_class("success")
            self.noop_copy = False

        GLib.timeout_add(1500, reset)

    def bind(self, row_data: ResultRowData | ErrorRowData, list_item: Gtk.ListItem, model: Gio.ListStore, parent: "MainWindow") -> None:
        self.path = row_data.path

        list_item.delete_handler_id = self.button_delete.connect("clicked", self._on_click_delete, list_item, model)
        self.button_delete.set_sensitive(True)

    def unbind(self, list_item: Gtk.ListItem, parent: "MainWindow") -> None:
        if hasattr(list_item, "delete_handler_id") and list_item.delete_handler_id > 0:
            self.button_delete.disconnect(list_item.delete_handler_id)
            list_item.delete_handler_id = 0
        self.button_delete.set_sensitive(False)


class HashResultRow(HashRow):
    __gtype_name__ = "HashResultRow"
    base_path: Path
    hash_value: str
    algo: str

    def __init__(self):
        super().__init__()
        self.prefix_icon.set_from_icon_name("dialog-password-symbolic")
        self.hash_icon_name = self.prefix_icon.get_icon_name()

        self.button_multi_hash = self._create_button(None, "Select and compute multiple hash algorithms for this file", None)
        self.button_multi_hash.set_child(Gtk.Label(label="Multi-Hash"))
        self.button_copy_hash = self._create_button("edit-copy-symbolic", "Copy hash", None)
        self.button_compare = self._create_button("edit-paste-symbolic", "Compare with clipboard", None)
        self.button_delete = self._create_button("user-trash-symbolic", "Remove this result", None)

    def _set_icon_(self, icon_name: Literal["text-x-generic-symbolic", "object-select-symbolic", "dialog-error-symbolic"]):
        self.prefix_icon.set_from_icon_name(icon_name)

    def _reset_icon(self) -> None:
        self._set_icon_(self.hash_icon_name)

    def _reset_css(self) -> None:
        self.remove_css_class("custom-success")
        self.remove_css_class("custom-error")

    def bind(self, row_data: ResultRowData, list_item: Gtk.ListItem, model: Gio.ListStore, parent: "MainWindow") -> None:
        super().bind(row_data, list_item, model, parent)
        self.base_path = row_data.base_path
        self.algo = row_data.algo
        self.hash_value = row_data.hash_value

        self.prefix_label.set_label(row_data.algo.upper())
        list_item.path_display_binding = row_data.bind_property("path_display", self.title, "label", GObject.BindingFlags.SYNC_CREATE)
        list_item.path_display_handler_id = parent.connect("call-row-data", row_data.signal_handler)
        self.subtitle.set_text(self.hash_value)

        list_item.multi_hash_handler_id = self.button_multi_hash.connect("clicked", parent._on_multi_hash_requested, self)
        list_item.copy_handler_id = self.button_copy_hash.connect("clicked", self._on_click_copy, "success")
        list_item.compare_handler_id = self.button_compare.connect("clicked", parent._on_clipboard_compare_requested, self)

    def unbind(self, list_item: Gtk.ListItem, parent: "MainWindow") -> None:
        super().unbind(list_item, parent)
        list_item.path_display_binding.unbind()
        parent.disconnect(list_item.path_display_handler_id)
        self.button_multi_hash.disconnect(list_item.multi_hash_handler_id)
        self.button_copy_hash.disconnect(list_item.copy_handler_id)
        self.button_compare.disconnect(list_item.compare_handler_id)


class HashErrorRow(HashRow):
    __gtype_name__ = "HashErrorRow"
    error_message: str

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.prefix_icon.set_from_icon_name("dialog-error-symbolic")
        self.prefix_label.set_visible(False)
        self.button_copy_error = self._create_button("edit-copy-symbolic", "Copy error message", None)
        self.button_delete = self._create_button("user-trash-symbolic", "Remove this error", None)
        self.add_css_class("custom-error")

    def bind(self, row_data: ErrorRowData, list_item: Gtk.ListItem, model: Gio.ListStore, parent: "MainWindow") -> None:
        super().bind(row_data, list_item, model, parent)
        self.error_message = row_data.error_message
        self.title.set_text(self.path)
        self.subtitle.set_text(self.error_message)

        list_item.copy_handler_id = self.button_copy_error.connect("clicked", self._on_click_copy)

    def unbind(self, list_item: Gtk.ListItem, parent: "MainWindow") -> None:
        super().unbind(list_item, parent)
        self.button_copy_error.disconnect(list_item.copy_handler_id)


class MultiHashDialog(Adw.AlertDialog):
    def __init__(self, parent: "MainWindow", data: "HashResultRow", working_config: dict, **kwargs):
        super().__init__(**kwargs)
        body = "<big><b>Select Additional Algorithms</b></big>\n"
        body = f"{body}<small>Choose one or more algorithms to run in addition to the calculated one.</small>"
        self.set_body(body)
        self.set_body_use_markup(True)
        self.set_presentation_mode(Adw.DialogPresentationMode.BOTTOM_SHEET)
        self.add_response("cancel", "Cancel")
        self.add_response("compute", "Compute")
        self.set_response_appearance("compute", Adw.ResponseAppearance.SUGGESTED)
        self.set_response_enabled("compute", False)
        self.set_close_response("cancel")

        vertical_main_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_extra_child(vertical_main_container)

        display_row = HashRow()
        display_row.add_css_class("darker-action-row")
        display_row.prefix_icon.set_from_icon_name("folder-documents-symbolic")
        display_row.remove(display_row.prefix_label)
        display_row.title.set_text(data.path.name)
        display_row.subtitle.set_text(f"{data.algo.upper()}  {data.hash_value}")
        display_row.set_margin_bottom(5)
        vertical_main_container.append(display_row)

        horizontal_container_checkbuttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=15, css_classes=["custom-style-row"])
        vertical_main_container.append(horizontal_container_checkbuttons)

        horizontal_container_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, halign=Gtk.Align.END, spacing=6)
        vertical_main_container.append(horizontal_container_buttons)

        select_all_button = Gtk.Button(label="Select All", css_classes=["flat"])
        horizontal_container_buttons.append(select_all_button)

        deselect_all_button = Gtk.Button(label="Deselect All", css_classes=["flat"])
        horizontal_container_buttons.append(deselect_all_button)

        checkbuttons: list[Gtk.CheckButton] = []
        can_compute = lambda *_: self.set_response_enabled("compute", any(c.get_active() for c in checkbuttons))
        on_button_click = lambda _, state: list(c.set_active(state) for c in checkbuttons)

        count = 0
        for algo in AVAILABLE_ALGORITHMS:
            if algo == data.algo:
                continue

            if count % 5 == 0:
                current_check_box_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
                horizontal_container_checkbuttons.append(current_check_box_container)

            checkbutton = Gtk.CheckButton()
            checkbutton.set_child(Gtk.Label(label=algo.replace("_", "-").upper()))
            checkbutton.algo = algo
            checkbutton.connect("notify::active", can_compute)

            checkbuttons.append(checkbutton)
            current_check_box_container.append(checkbutton)
            count += 1

        select_all_button.connect("clicked", on_button_click, True)
        deselect_all_button.connect("clicked", on_button_click, False)

        def on_response(_, response_id):
            if response_id == "compute":
                selected_algos = [c.algo for c in checkbuttons if c.get_active()]
                repeat_n_times = len(selected_algos)
                parent.start_job(
                    repeat(data.base_path, repeat_n_times),
                    repeat(data.path, repeat_n_times),
                    selected_algos,
                    working_config,
                )

        self.connect("response", on_response)
        self.present(parent)


class MainWindow(Adw.ApplicationWindow):
    __gtype_name__ = "MainWindow"
    __gsignals__ = {"call-row-data": (GObject.SignalFlags.RUN_FIRST, None, (GObject.TYPE_PYOBJECT,))}
    DEFAULT_WIDTH = 970
    DEFAULT_HEIGHT = 650

    def __init__(self, app: "QuickFileHasher"):
        super().__init__(application=app, title="Quick File Hasher")
        self.set_default_size(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        self.logger = get_logger(self.__class__.__name__)
        self.app = app
        self.pref = app.pref
        self.pref.connect("call-main-window", self.signal_handler)
        self.connect("close-request", self._on_close_request)

        self._create_actions()
        self._build_ui()

        self.queue_handler = QueueUpdateHandler()
        self.cancel_event = threading.Event()
        self._calculate_hashes = CalculateHashes(self.queue_handler, self.cancel_event)

    def signal_handler(self, emitter: Any, args: list) -> None:
        args_copy = args.copy()
        action = args_copy.pop(0)
        if action == "trigger-on-items-changed":
            self.on_items_changed()

        elif action == "trigger-path-update":
            use_relative_path = args_copy.pop(0)
            self.emit("call-row-data", [action, use_relative_path])

    def _build_ui(self) -> None:
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        self.overlay = Gtk.Overlay()
        self.toast_overlay.set_child(self.overlay)

        self._setup_search()
        self.overlay.add_overlay(self.search_entry)

        self._setup_drag_and_drop()
        self.overlay.add_overlay(self.dnd_revealer)

        self.toolbar_view = Adw.ToolbarView(margin_top=6, margin_bottom=6, margin_start=12, margin_end=12)
        self.overlay.set_child(self.toolbar_view)

        self._setup_first_top_bar()
        self.toolbar_view.add_top_bar(self.first_top_bar_box)

        self._setup_second_top_bar()
        self.toolbar_view.add_top_bar(self.second_top_bar_box)

        self._setup_content()
        self.toolbar_view.set_content(self.content_overlay)

        self._setup_bottom_bar()
        self.toolbar_view.add_bottom_bar(self.progress_bar)

    def _setup_search(self) -> None:
        self.search_query = ""
        self.search_entry = Gtk.SearchEntry(
            placeholder_text="Type to filter & ESC to clear",
            margin_start=10,
            margin_end=10,
            margin_bottom=20,
            valign=Gtk.Align.END,
            visible=False,
            css_classes=["search-bg-color"],
        )

    def _setup_drag_and_drop(self) -> None:
        self.dnd_status_page = Adw.StatusPage(
            title="Drop Files Here",
            icon_name="document-send-symbolic",
            css_classes=["drag-overlay"],
        )
        self.dnd_revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.CROSSFADE,
            reveal_child=False,
            can_target=False,
            child=self.dnd_status_page,
        )

        self.drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        self.drop.connect("enter", lambda *_: (self.dnd_revealer.set_reveal_child(True), Gdk.DragAction.COPY)[1])
        self.drop.connect("leave", lambda *_: self.dnd_revealer.set_reveal_child(False))

        def on_drop(ctrl, drop: Gdk.FileList, x, y, user_data=None) -> bool:
            self.dnd_revealer.set_reveal_child(False)
            try:
                files = [Path(file.get_path()) for file in drop.get_files()]
                self.start_job(None, files, repeat(self.pref.get_algorithm()), self.pref.get_working_config())
                return True
            except Exception as e:
                self.add_toast(f"Drag & Drop failed: {e}")
                return False

        self.drop.connect("drop", on_drop)
        self.add_controller(self.drop)

    def _setup_first_top_bar(self) -> None:
        self.first_top_bar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, margin_bottom=10)

        self.button_select_files = self._create_button("Select Files", "document-open-symbolic", "Select files to add", "suggested-action", self._on_select_files_or_folders_clicked, True)
        self.first_top_bar_box.append(self.button_select_files)

        self.button_select_folders = self._create_button("Select Folders", "folder-symbolic", "Select folders to add", "suggested-action", self._on_select_files_or_folders_clicked, False)
        self.first_top_bar_box.append(self.button_select_folders)

        self.button_save = self._create_button("Save", "document-save-symbolic", "Save results to file", "suggested-action", self._on_save_clicked)
        self.button_save.set_sensitive(False)

        self.first_top_bar_box.append(self.button_save)

        callback = lambda _: (self.cancel_event.set(), self.add_toast("❌ Jobs Cancelled"))
        self.button_cancel = self._create_button("Cancel Jobs", None, None, "destructive-action", callback)
        self.button_cancel.set_visible(False)
        self.first_top_bar_box.append(self.button_cancel)

        spacer_0 = Gtk.Box()
        spacer_0.set_hexpand(True)
        self.first_top_bar_box.append(spacer_0)

        self._setup_header_bar()
        self.first_top_bar_box.append(self.header_bar)

    def _setup_second_top_bar(self) -> None:
        self.second_top_bar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, margin_bottom=8)

        self.view_switcher = Adw.ViewSwitcher(hexpand=True, policy=Adw.ViewSwitcherPolicy.WIDE, css_classes=["view-switcher"])
        self.second_top_bar_box.append(self.view_switcher)

        spacer_1 = Gtk.Box(hexpand=True)
        self.second_top_bar_box.append(spacer_1)

        self.button_copy_all = self._create_button("Copy", None, "Copy results to clipboard", "suggested-action", self._on_copy_all_clicked)
        self.button_copy_all.set_sensitive(False)
        self.second_top_bar_box.append(self.button_copy_all)

        self.toggle_button_sort = Gtk.ToggleButton(
            label="Sort",
            tooltip_text="Sort results by path",
            css_classes=["custom-toggle-btn"],
            sensitive=False,
            valign=Gtk.Align.CENTER,
        )
        self.toggle_button_sort.connect("toggled", self._on_sort_toggled)
        self.second_top_bar_box.append(self.toggle_button_sort)

        self.button_clear = self._create_button("Clear", None, "Clear all results", "destructive-action", self._on_clear_clicked)
        self.button_clear.set_sensitive(False)
        self.second_top_bar_box.append(self.button_clear)

    def _setup_header_bar(self) -> None:
        self.header_bar = Adw.HeaderBar(
            title_widget=Gtk.Label(label="<big><b>Quick File Hasher</b></big>", use_markup=True),
        )
        self._setup_menu()
        self._setup_search_button()

    def _setup_results_view(self) -> None:
        self.results_model = Gio.ListStore.new(ResultRowData)
        self.results_model.connect("items-changed", self._on_items_changed)

        self.results_custom_sorter = Gtk.CustomSorter.new(self._sort_by_hierarchy, self.toggle_button_sort)
        self.results_model_sorted = Gtk.SortListModel.new(self.results_model, self.results_custom_sorter)

        self.results_custom_filter = Gtk.CustomFilter.new(self._filter_func)
        self.results_model_filtered = Gtk.FilterListModel.new(self.results_model_sorted, self.results_custom_filter)
        self.search_entry.connect("search-changed", self._on_search_changed, self.results_model, self.results_custom_filter)

        self.results_model_selection = Gtk.NoSelection.new(self.results_model_filtered)
        self.results_model_selection.connect("selection-changed", self._on_selection_changed)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup, "result")
        factory.connect("bind", self._on_factory_bind)
        factory.connect("unbind", self._on_factory_unbind)
        self.results_list_view = Gtk.ListView(model=self.results_model_selection, factory=factory, css_classes=["no-background"])

        self.results_scrolled_window = Gtk.ScrolledWindow(child=self.results_list_view, hscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vscrollbar_policy=Gtk.PolicyType.AUTOMATIC)

    def _setup_errors_view(self) -> None:
        self.errors_model = Gio.ListStore.new(ErrorRowData)
        self.errors_model.connect("items-changed", self._on_items_changed)

        self.errors_custom_filter = Gtk.CustomFilter.new(self._filter_func)
        self.errors_model_filtered = Gtk.FilterListModel.new(self.errors_model, self.errors_custom_filter)
        self.search_entry.connect("search-changed", self._on_search_changed, self.errors_model, self.errors_custom_filter)

        self.errors_selection_model = Gtk.NoSelection(model=self.errors_model_filtered)
        self.errors_selection_model.connect("selection-changed", self._on_selection_changed)

        factory_err = Gtk.SignalListItemFactory()
        factory_err.connect("setup", self._on_factory_setup, "error")
        factory_err.connect("bind", self._on_factory_bind)
        factory_err.connect("unbind", self._on_factory_unbind)
        self.errors_list_view = Gtk.ListView(model=self.errors_selection_model, factory=factory_err, css_classes=["no-background"])

        self.errors_scrolled_window = Gtk.ScrolledWindow(child=self.errors_list_view, hscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vscrollbar_policy=Gtk.PolicyType.AUTOMATIC)

    def _setup_content(self) -> None:
        self.content_overlay = Gtk.Overlay()

        self.empty_placeholder = Adw.StatusPage(title="No Results", description="Select files or folders to calculate their hashes.", icon_name="text-x-generic-symbolic")
        self.view_stack = Adw.ViewStack(visible=False)
        self.view_switcher.set_stack(self.view_stack)

        self.content_overlay.add_overlay(self.view_stack)
        self.content_overlay.add_overlay(self.empty_placeholder)

        self._setup_results_view()
        self.results_stack_page = self.view_stack.add_titled_with_icon(self.results_scrolled_window, "results", "Results", "view-list-symbolic")
        self._setup_errors_view()
        self.errors_stack_page = self.view_stack.add_titled_with_icon(self.errors_scrolled_window, "errors", "Errors", "dialog-error-symbolic")

        self.view_stack.connect("notify::visible-child", self.on_items_changed)

    def _setup_menu(self) -> None:
        menu = Gio.Menu()
        menu.append("Preferences", "app.preferences")
        menu.append("Keyboard Shortcuts", "app.shortcuts")
        menu.append("About", "app.about")
        menu.append("Quit", "win.quit")
        button_menu = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        self.header_bar.pack_end(button_menu)

    def _setup_search_button(self) -> None:
        self.button_show_searchbar = Gtk.Button(
            tooltip_text="Show search bar to filter results and errors",
            sensitive=False,
            icon_name="system-search-symbolic",
        )
        self.button_show_searchbar.connect("clicked", lambda _: self._on_click_show_searchbar(not self.search_entry.is_visible()))
        self.header_bar.pack_end(self.button_show_searchbar)

    def _setup_bottom_bar(self) -> None:
        self.progress_bar = Gtk.ProgressBar(opacity=0, margin_top=2)

    def _create_button(self, label: str, icon_name: str, tooltip_text: str, css_class: str, callback: Callable | None, *args) -> Gtk.Button:
        button = Gtk.Button(valign=Gtk.Align.CENTER, tooltip_text=tooltip_text)
        if css_class:
            button.add_css_class(css_class)

        if callback:
            button.connect("clicked", callback, *args)

        if icon_name:
            button_content = Adw.ButtonContent(icon_name=icon_name, label=label)
            button.set_child(button_content)

        else:
            button.set_label(label)

        return button

    def _modify_placeholder(self, current_page_name: str) -> bool:
        title = "No Results" if current_page_name == "results" else "No Errors"
        current_title = self.empty_placeholder.get_title()
        if current_title == title:
            return False
        icon_name = "text-x-generic-symbolic" if current_page_name == "results" else "object-select-symbolic"
        description = "Select files or folders to calculate their hashes." if current_page_name == "results" else " "
        self.empty_placeholder.set_title(title)
        self.empty_placeholder.set_icon_name(icon_name)
        self.empty_placeholder.set_description(description)
        return True

    def _sort_by_hierarchy(self, row1: ResultRowData, row2: ResultRowData, sort_enabled: Gtk.ToggleButton) -> int:
        """
        - /folder/a.txt
        - /folder/z.txt
        - /folder/subfolder_b/
        - /folder/subfolder_b/file.txt
        - /folder/subfolder_y/
        """
        if not sort_enabled.get_active():
            return 0

        p1, p2 = row1.path, row2.path

        if p1.parent.parts != p2.parent.parts:
            return -1 if p1.parent.parts < p2.parent.parts else 1

        if p1.name != p2.name:
            return -1 if p1.name < p2.name else 1
        return 0

    def start_job(
        self,
        base_paths: Iterable[Path] | None,
        paths: Iterable[Path],
        hashing_algorithms: Iterable[str],
        options: dict,
    ) -> None:
        self.cancel_event.clear()
        self.button_cancel.set_visible(True)
        self.progress_bar.set_opacity(1.0)

        threading.Thread(
            target=self._calculate_hashes,
            args=(base_paths or paths, paths, hashing_algorithms, options),
            daemon=True,
        ).start()
        self._run_every_n_ms_in_background(0.01, self._process_queue, self.pref.use_relative_paths())

    def _run_every_n_ms_in_background(self, interval: float, callback: Callable[..., bool], *args, **kwargs):
        def loop():
            while True:
                keep_going = callback(*args, **kwargs)
                if not keep_going:
                    break
                time.sleep(interval)

        threading.Thread(target=loop, daemon=True).start()

    def _process_queue(self, use_relative_paths: bool) -> bool:
        queue_empty = self.queue_handler.is_empty()
        job_done = self.progress_bar.get_fraction() == 1.0

        if self.cancel_event.is_set() or (queue_empty and job_done):
            self._processing_complete()
            return False

        new_rows = []
        new_errors = []
        iterations = 0
        while iterations < 100:
            try:
                update = self.queue_handler.get_update()
            except Empty:
                break

            kind = update[0]
            if kind == "progress":
                GLib.idle_add(self.progress_bar.set_fraction, update[1])

            elif kind == "result":
                iterations += 1
                new_rows.append(ResultRowData(*update[1:], use_relative_paths))

            elif kind == "error":
                iterations += 1
                new_errors.append(ErrorRowData(*update[1:]))

            elif kind == "toast":
                GLib.idle_add(self.add_toast, update[1])

        if new_rows:
            GLib.idle_add(self._add_rows, self.results_model, new_rows)
        if new_errors:
            GLib.idle_add(self._add_rows, self.errors_model, new_errors)

        return True  # Continue monitoring

    def _add_rows(self, model: Gio.ListStore, rows: list) -> None:
        model.splice(model.get_n_items(), 0, rows)

    def _processing_complete(self) -> None:
        if self.cancel_event.is_set():
            self.queue_handler.reset()

        self._calculate_hashes.reset_counters()
        self.button_cancel.set_visible(False)
        self._hide_progress()

    def _hide_progress(self) -> None:
        self._animate_opacity(self.progress_bar, 1, 0, 500)
        GLib.timeout_add(500, self.progress_bar.set_fraction, 0.0, priority=GLib.PRIORITY_DEFAULT)
        GLib.timeout_add(1000, self._scroll_to_bottom, priority=GLib.PRIORITY_DEFAULT)

    def _update_badge_numbers(self) -> None:
        self.results_stack_page.set_badge_number(self.results_model.get_n_items())
        self.errors_stack_page.set_badge_number(self.errors_model.get_n_items())

    def _scroll_to_bottom(self) -> None:
        vadjustment = self.results_scrolled_window.get_vadjustment()
        current_value = vadjustment.get_value()
        target_value = vadjustment.get_upper() - vadjustment.get_page_size()
        Adw.TimedAnimation(
            widget=self,
            value_from=current_value,
            value_to=target_value,
            duration=250,
            target=Adw.CallbackAnimationTarget.new(lambda value: vadjustment.set_value(value)),
        ).play()

    def _animate_opacity(self, widget: Gtk.Widget, from_value: float, to_value: float, duration: int) -> None:
        animation = Adw.TimedAnimation.new(
            self,
            from_value,
            to_value,
            duration,
            Adw.CallbackAnimationTarget.new(lambda opacity: widget.set_opacity(opacity)),
        )
        animation.play()

    def on_items_changed(self, view_stack: Adw.ViewStack = None, param: GObject.ParamSpec = None) -> None:
        has_results = self.results_model.get_n_items() > 0
        has_errors = self.errors_model.get_n_items() > 0
        save_errors = self.pref.save_errors()
        current_page_name = self.view_stack.get_visible_child_name()

        can_save_or_copy = has_results or (has_errors and save_errors)
        can_clear_or_search = has_results or has_errors
        self.button_save.set_sensitive(can_save_or_copy)
        self.button_copy_all.set_sensitive(can_save_or_copy)
        self.toggle_button_sort.set_sensitive(has_results)
        self.button_clear.set_sensitive(can_clear_or_search)
        self.button_show_searchbar.set_sensitive(can_clear_or_search)
        self._update_badge_numbers()

        show_empty = (current_page_name == "results" and not has_results) or (current_page_name == "errors" and not has_errors)
        target_modified = False
        if show_empty:
            target_modified = self._modify_placeholder(current_page_name)
            target = self.empty_placeholder
        else:
            target = self.view_stack

        if not target.is_visible() or (view_stack and param) or (target.is_visible() and target_modified):
            Adw.TimedAnimation(
                widget=self,
                value_from=0.3,
                value_to=1.0,
                duration=250,
                target=Adw.CallbackAnimationTarget.new(lambda opacity: target.set_opacity(opacity)),
            ).play()

        self.view_stack.set_visible(not show_empty)
        self.empty_placeholder.set_visible(show_empty)

    def _txt_to_file(self, output: str | None) -> None:
        if output is None:
            self.add_toast("❌ Nothing to save")
            return
        file_dialog = Gtk.FileDialog(title="Save", initial_name="results.txt")

        def on_file_dialog_dismissed(file_dialog: Gtk.FileDialog, gio_task: Gio.Task) -> None:
            if not gio_task.had_error():
                try:
                    local_file = file_dialog.save_finish(gio_task)
                    path: str = local_file.get_path()

                    with open(path, "w", encoding="utf-8") as f:
                        f.write(output)

                    self.add_toast(f"✅ Saved to <b>{path}</b>")

                except Exception as e:
                    self.logger.error(f"Unexcepted error occured for {path}: {e}")
                    self.add_toast(f"❌ Failed to save: {e}")

        file_dialog.save(parent=self, callback=on_file_dialog_dismissed)

    def _txt_to_clipboard(self, output: str | None):
        if output:
            cp = Gdk.ContentProvider.new_for_bytes(
                "text/plain;charset=utf-8",
                GLib.Bytes.new(output.encode("utf-8")),
            )
            self.get_clipboard().set_content(cp)
            self.add_toast("✅ Results copied to clipboard")
        else:
            self.add_toast("❌ Nothing to copy")

    def _results_to_txt(self, callback: Callable[[str | None], None]) -> None:
        def worker():
            parts = []
            total_results = self.results_model_filtered.get_n_items()
            total_errors = self.errors_model_filtered.get_n_items()

            if total_results > 0:
                format_style = self.pref.get_format_style()
                results_txt = "\n".join(r(format_style) for r in self.results_model_filtered)
                parts.append(f"# Results ({total_results}):\n\n{results_txt}")

            if self.pref.save_errors() and total_errors > 0:
                errors_txt = "\n".join(str(r) for r in self.errors_model_filtered)
                parts.append(f"# Errors ({total_errors}):\n\n{errors_txt}")

            if self.pref.include_time() and parts:
                now = datetime.now().astimezone().strftime("%B %d, %Y at %H:%M:%S %Z")
                parts.append(f"# Generated on {now}")

            if parts:
                output = "\n\n".join(parts)
            else:
                output = None

            GLib.idle_add(callback, output)

        threading.Thread(target=worker, daemon=True).start()

    def _on_factory_setup(self, factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem, kind: str) -> None:
        row_widget = HashResultRow() if kind == "result" else HashErrorRow()
        list_item.set_selectable(False)
        list_item.set_activatable(False)
        list_item.set_focusable(False)
        list_item.set_child(row_widget)

    def _on_factory_bind(self, factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        row_widget: HashResultRow | HashErrorRow = list_item.get_child()
        row_data: ResultRowData | ErrorRowData = list_item.get_item()
        model = self.results_model if isinstance(row_widget, HashResultRow) else self.errors_model
        row_widget.bind(row_data, list_item, model, self)

    def _on_factory_unbind(self, factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        row_widget: HashResultRow | HashErrorRow = list_item.get_child()
        row_widget.unbind(list_item, self)

    def _on_items_changed(self, model: Gio.ListStore, position: int, removed: int, added: int) -> None:
        self.on_items_changed()

    def _on_selection_changed(self, selection_model: Gtk.MultiSelection, position: int, n_items: int) -> None:
        selected_items = []
        model = selection_model.get_model()

        for i in range(model.get_n_items()):
            if selection_model.is_selected(i):
                item = model.get_item(i)
                selected_items.append(item)

        print("Selected items:")
        for item in selected_items:
            print(item)

    def _on_multi_hash_requested(self, _: Gtk.Button, row: HashResultRow) -> None:
        MultiHashDialog(self, row, self.pref.get_working_config())

    def _on_clipboard_compare_requested(self, _: Gtk.Button, row: HashResultRow) -> None:
        if row.noop_cmp:
            return
        row.noop_cmp = True

        def handle_clipboard_comparison(clipboard: Gdk.Clipboard, result):
            try:
                clipboard_text: str = clipboard.read_text_finish(result).strip()

                if clipboard_text == row.hash_value:
                    row.add_css_class("custom-success")
                    row._set_icon_("object-select-symbolic")
                    self.add_toast(f"✅ Clipboard hash matches <b>{row.title.get_text()}</b>!")

                else:
                    row.add_css_class("custom-error")
                    row._set_icon_("dialog-error-symbolic")
                    self.add_toast(f"❌ The clipboard hash does <b>not</b> match <b>{row.title.get_text()}</b>!")

            except Exception as e:
                self.add_toast(f"❌ Clipboard read error: {e}")

            finally:

                def reset():
                    row._reset_css()
                    row._reset_icon()
                    row.noop_cmp = False

                GLib.timeout_add(3000, reset)

        clipboard = self.get_clipboard()
        clipboard.read_text_async(None, handle_clipboard_comparison)

    def _on_click_show_searchbar(self, show: bool) -> None:
        if self.button_show_searchbar.is_sensitive():
            self.search_entry.set_visible(show)
            if show:
                self.search_entry.grab_focus()
            else:
                self.search_entry.set_text("")
        else:
            self.add_toast("🔍 No Results. Search is unavailable.")

    def _on_select_files_or_folders_clicked(self, _: Gtk.Button, files: bool) -> None:
        title = "Select Files" if files else "Select Folders"
        file_dialog = Gtk.FileDialog(title=title)

        def on_files_dialog_dismissed(file_dialog: Gtk.FileDialog, gio_task: Gio.Task) -> None:
            if not gio_task.had_error():
                if files:
                    files_or_folders: list[Gio.File] = file_dialog.open_multiple_finish(gio_task)
                else:
                    files_or_folders: list[Gio.File] = file_dialog.select_multiple_folders_finish(gio_task)

                self.start_job(
                    None,
                    [Path(file.get_path()) for file in files_or_folders],
                    repeat(self.pref.get_algorithm()),
                    self.pref.get_working_config(),
                )

        if files:
            file_dialog.open_multiple(parent=self, callback=on_files_dialog_dismissed)
        else:
            file_dialog.select_multiple_folders(parent=self, callback=on_files_dialog_dismissed)

    def _on_copy_all_clicked(self, _: Gtk.Button) -> None:
        self._results_to_txt(self._txt_to_clipboard)

    def _on_save_clicked(self, _: Gtk.Button) -> None:
        self._results_to_txt(self._txt_to_file)

    def _on_clear_clicked(self, _: Gtk.Button) -> None:
        if self.button_clear.is_sensitive():
            self._on_click_show_searchbar(False)
            self.results_model.remove_all()
            self.errors_model.remove_all()
            self.add_toast("✅ Results cleared")

    def _on_search_changed(self, entry: Gtk.SearchEntry, model: Gio.ListStore, custom_filter: Gtk.Filter) -> None:
        self.search_query = entry.get_text().lower()
        threading.Thread(target=self._background_filter, args=(model, custom_filter), daemon=True).start()

    def _background_filter(self, model: Gio.ListStore, custom_filter: Gtk.Filter) -> None:
        visible_rows = set()
        if self.search_query:
            terms = self.search_query.split()
            for row in model:
                fields = row.get_search_fields()
                if all(any(term in field for field in fields) for term in terms):
                    visible_rows.add(row)

        GLib.idle_add(self._update_filter, custom_filter, visible_rows)

    def _update_filter(self, custom_filter: Gtk.Filter, visible_rows: set) -> None:
        self.visible_rows = visible_rows
        custom_filter.changed(Gtk.FilterChange.DIFFERENT)

    def _filter_func(self, row: ResultRowData | ErrorRowData) -> bool:
        if not self.search_query:
            return True
        return row in self.visible_rows

    def _on_sort_toggled(self, toggle: Gtk.ToggleButton) -> None:
        if toggle.get_active():
            self.add_toast("✅ Sort Enabled")
            self.results_custom_sorter.changed(Gtk.FilterChange.DIFFERENT)
        else:
            self.add_toast("❌ Sort Disabled")

    def _on_close_request(self, window: Adw.Window) -> bool:
        self.cancel_event.set()
        self.pref.disconnect_by_func(self.signal_handler)
        self._on_clear_clicked(window)

    def add_toast(self, toast_label: str, timeout: int = 2, priority=Adw.ToastPriority.NORMAL) -> None:
        toast = Adw.Toast(
            custom_title=Gtk.Label(
                label=toast_label,
                use_markup=True,
                ellipsize=Pango.EllipsizeMode.MIDDLE,
            ),
            timeout=timeout,
            priority=priority,
        )
        self.toast_overlay.add_toast(toast)

    def _create_actions(self) -> None:
        actions = (
            ("show-searchbar", lambda *_: self._on_click_show_searchbar(True), ["<Ctrl>F"]),
            ("hide-searchbar", lambda *_: self._on_click_show_searchbar(False), ["Escape"]),
            ("open-files", lambda *_: self._on_select_files_or_folders_clicked(_, files=True), ["<Ctrl>O"]),
            ("results-copy", lambda *_: self._on_copy_all_clicked(_), ["<Ctrl><Shift>C"]),
            ("results-save", lambda *_: self._on_save_clicked(_), ["<Ctrl>S"]),
            ("results-sort", lambda *_: self.toggle_button_sort.set_active(not self.toggle_button_sort.get_active()), ["<Ctrl>R"]),
            ("results-clear", lambda *_: self._on_clear_clicked(_), ["<Ctrl>L"]),
            ("quit", lambda *_: self.close(), ["<Ctrl>Q"]),
        )

        for name, callback, accels in actions:
            self._create_win_action(name, callback, accels)

    def _create_win_action(self, name: str, callback: Callable, accels: list[str] | None = None) -> None:
        action = Gio.SimpleAction.new(name=name, parameter_type=None)
        action.connect("activate", callback)
        self.add_action(action=action)
        if accels:
            self.app.set_accels_for_action(f"win.{name}", accels)


class QuickFileHasher(Adw.Application):
    __gtype_name__ = "QuickFileHasher"

    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE | Gio.ApplicationFlags.HANDLES_OPEN)
        self.logger = get_logger(self.__class__.__name__)
        self.pref = Preferences()
        self.pref.connect("call-application", self.signal_handler)

        self._create_actions()
        self._create_options()
        self._setup_about()
        self._setup_shortcuts()

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)

    def do_shutdown(self) -> None:
        self.logger.debug("Application shutdown")
        Adw.Application.do_shutdown(self)

    def do_handle_local_options(self, options: GLib.VariantDict) -> int:
        self.logger.debug("Application handle local options")
        if options.contains("list-choices"):
            for i, algo in enumerate(AVAILABLE_ALGORITHMS):
                if i % 4 == 0 and i > 0:
                    print()
                print(f"{algo:<15}", end="")
            print()
            return 0
        return -1  # Continue

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        cli_options: dict = command_line.get_options_dict().end().unpack()
        self.logger.debug(f"Initial CLI options: {cli_options}")

        from_cli = "DESKTOP" not in cli_options
        new_window = "new-window" in cli_options
        paths = command_line.get_arguments()[1:]

        if from_cli:
            _config_ = self.pref.get_persisted_config()
            algo = cli_options.get("algo") or _config_.get("algo")

            if algo not in AVAILABLE_ALGORITHMS:
                print(f"Unexpected hash algorithm: {algo}")
                return 1

            _config_.update(
                recursive=cli_options.pop("recursive", False),
                gitignore=cli_options.pop("gitignore", False),
                **cli_options,
            )

            if not paths:
                self.pref.apply_config_ui(_config_)

        else:
            _config_ = self.pref.get_working_config()

        if paths:
            cwd = command_line.get_cwd()
            paths = [Path(cwd) / path for path in paths]
            self.do_open(paths, len(paths), _config_.get("algo"), _config_, new_window)

        else:
            self.do_activate(new_window)

        self.logger.debug(f"Effective CLI options out: {_config_}")
        return 0

    def do_activate(self, new_window: bool) -> None:
        self.logger.debug(f"App {self.get_application_id()} activated")
        main_window = self.get_active_window()
        if not main_window or new_window:
            main_window = MainWindow(self)
        main_window.present()

    def do_open(self, paths: Iterable[Path], n_files: int, hash_algorithm: str, options: dict, new_window: bool) -> None:
        self.logger.debug(f"App {self.get_application_id()} opened with files ({n_files})")
        main_window = self.get_active_window()
        if not main_window or new_window:
            main_window = MainWindow(self)
        main_window.present()
        main_window.start_job(None, paths, repeat(hash_algorithm), options)

    def on_preferences(self, action: Gio.SimpleAction, param: GLib.Variant | None) -> None:
        active_window = self.get_active_window()
        if active_window:
            self.pref.set_transient_for(active_window)
            self.pref.present()

    def on_shortcuts(self, action: Gio.SimpleAction, param: GLib.Variant | None) -> None:
        active_window = self.get_active_window()
        if active_window:
            self.shortcuts.set_transient_for(active_window)
            self.shortcuts.present()

    def on_about(self, action: Gio.SimpleAction, param: GLib.Variant | None) -> None:
        active_window = self.get_active_window()
        if active_window:
            self.about.set_transient_for(active_window)
            self.about.present()

    def signal_handler(self, emitter: Any, args: list) -> None:
        # TODO
        pass

    def _setup_about(self) -> None:
        self.about = Adw.AboutWindow(
            hide_on_close=True,
            modal=True,
            application_name="Quick File Hasher",
            application_icon=APP_ID,
            version=APP_VERSION,
            developer_name="Doğukan Doğru",
            license_type=Gtk.License(Gtk.License.MIT_X11),
            comments="Verify your files with speed and confidence.",
            website="https://github.com/dd-se/nautilus-extension-quick-file-hasher",
            issue_url="https://github.com/dd-se/nautilus-extension-quick-file-hasher/issues",
            copyright="© 2025 Doğukan Doğru",
            developers=["Doğukan Doğru https://github.com/dd-se"],
            designers=["Doğukan Doğru https://github.com/dd-se"],
        )

    def _setup_shortcuts(self) -> None:
        shortcuts = [
            {
                "title": "File Operations",
                "shortcuts": [
                    {"title": "Open Files", "accelerator": "<Ctrl>O"},
                    {"title": "Save Results", "accelerator": "<Ctrl>S"},
                    {"title": "Close Window", "accelerator": "<Ctrl>Q"},
                ],
            },
            {
                "title": "View & Search",
                "shortcuts": [
                    {"title": "Show Search Bar", "accelerator": "<Ctrl>F"},
                    {"title": "Hide Search Bar", "accelerator": "Escape"},
                    {"title": "Toggle Sort", "accelerator": "<Ctrl>R"},
                    {"title": "Clear All Results", "accelerator": "<Ctrl>L"},
                ],
            },
            {
                "title": "Clipboard",
                "shortcuts": [
                    {"title": "Copy All Results", "accelerator": "<Ctrl><Shift>C"},
                ],
            },
        ]

        self.shortcuts = Gtk.ShortcutsWindow(title="Shortcuts", modal=True, hide_on_close=True)

        shortcuts_section = Gtk.ShortcutsSection(section_name="shortcuts", max_height=12)

        for group in shortcuts:
            shortcuts_group = Gtk.ShortcutsGroup(title=group["title"])

            for shortcut in group["shortcuts"]:
                shortcuts_group.add_shortcut(Gtk.ShortcutsShortcut(title=shortcut["title"], accelerator=shortcut["accelerator"]))

            shortcuts_section.add_group(shortcuts_group)

        self.shortcuts.add_section(shortcuts_section)

    def _create_actions(self) -> None:
        self._create_action("preferences", self.on_preferences, shortcuts=["<Ctrl>comma"])
        self._create_action("shortcuts", self.on_shortcuts, shortcuts=["<Ctrl>question"])
        self._create_action("about", self.on_about)

    def _create_action(
        self,
        name: str,
        callback: Callable,
        parameter_type: GLib.VariantType | None = None,
        shortcuts: list[str] | None = None,
    ) -> None:
        action = Gio.SimpleAction.new(name=name, parameter_type=parameter_type)
        action.connect("activate", callback)
        self.add_action(action=action)
        if shortcuts:
            self.set_accels_for_action(
                detailed_action_name=f"app.{name}",
                accels=shortcuts,
            )

    def _create_options(self) -> None:
        self.set_option_context_summary("Quick File Hasher - Verify your files with speed and confidence")
        self.set_option_context_parameter_string("[FILE|FOLDER...] [--recursive] [--gitignore] [--max-workers 4] [--algo sha256]")
        self.add_main_option("algo", ord("a"), GLib.OptionFlags.NONE, GLib.OptionArg.STRING, "Default hashing algorithm", "ALGORITHM")
        self.add_main_option("recursive", ord("r"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE, "Process files within subdirectories", None)
        self.add_main_option("gitignore", ord("g"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE, "Skip files/folders listed in .gitignore", None)
        self.add_main_option("max-workers", ord("w"), GLib.OptionFlags.NONE, GLib.OptionArg.INT, "Maximum number of parallel hashing operations", "N")
        self.add_main_option("list-choices", ord("l"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE, "List available hash algorithms", None)
        self.add_main_option("new-window", ord("n"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE, "Open in a new window", None)
        self.add_main_option("DESKTOP", 0, GLib.OptionFlags.HIDDEN, GLib.OptionArg.NONE, "Invoked from the Desktop Environment", None)


if __name__ == "__main__":
    app = QuickFileHasher()
    app.run(sys.argv)
