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
APP_NAME = "Quick File Hasher"
APP_VERSION = "1.9.5"

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
    "uppercase-hash": False,
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
toast { background-color: #000000; }
listview row:selected { background-color: shade(@accent_bg_color, 0.8); }

.custom-success { color: #57EB72; }
.custom-error { color: #FF938C; }

.view-switcher button {
    background-color: shade(@theme_bg_color, 1.32);
    color: @theme_fg_color;
    margin: 0 6px;
    min-height: 35px;
    min-width: 200px;
    transition: background-color 0.3s ease, color 0.3s ease;
}
.view-switcher button:nth-child(1):hover { background-color: #4a8de0; color: @accent_fg_color; }
.view-switcher button:nth-child(1):checked { background-color: #3074cf; color: @accent_fg_color; }
.view-switcher button:nth-child(2):hover { background-color: #20a13a; color: @accent_fg_color; }
.view-switcher button:nth-child(2):checked { background-color: #0E8825; color: @accent_fg_color; }
.view-switcher button:nth-child(3):hover { background-color: #e03445; color: @accent_fg_color; }
.view-switcher button:nth-child(3):checked { background-color: #c7162b; color: @accent_fg_color; }

.no-background { background-color: transparent; }
.background-light { background-color: shade(@theme_bg_color, 1.32); }
.background-dark { background-color: rgba(0, 0, 0, 0.2); }

.padding-small { padding-top: 2px; padding-left : 2px; padding-right : 2px; padding-bottom: 2px; }
.padding-large { padding-top: 8px; padding-left : 8px; padding-right : 8px; padding-bottom: 8px; }

.dnd-overlay { background-color: alpha(@accent_bg_color, 0.5); color: @accent_fg_color; }
.custom-toggle-btn:checked { background: shade(@theme_selected_bg_color,0.9); }
.custom-banner-theme { background-color: shade(@theme_bg_color, 1.32); color: @accent_fg_color; font-weight: bold; }

.custom-glow { transition: background-color 200ms ease; }
.custom-glow:hover { background-color: shade(@theme_bg_color, 1.60); }

.border-small { border: 1px solid shade(@theme_bg_color, 0.8); }
.rounded-medium { border-radius: 6px; }
.rounded-top { border-top-left-radius: 8px; border-top-right-radius: 8px; }
.rounded-top-small { border-top-left-radius: 4px; border-top-right-radius: 4px; }
.rounded-bottom { border-bottom-left-radius: 8px; border-bottom-right-radius: 8px; }
.rounded-bottom-small { border-bottom-left-radius: 4px; border-bottom-right-radius: 4px; }
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

    def _simple_hash_item(self, caller: str, hash_name: str, files: list[str]) -> Nautilus.MenuItem:
        """Hash Simple ()"""
        label = hash_name.replace("_", "-").upper() if hash_name else "DEFAULT"

        simple_hash_item = Nautilus.MenuItem(name=f"{label}_Simple_{caller}", label=label)
        simple_hash_item.connect("activate", self.nautilus_launch_app, files, hash_name, False)
        return simple_hash_item

    def _recursive_hash_item(self, caller: str, hash_name: str, files: list[str]) -> Nautilus.MenuItem:
        """Hash Recursive ()"""
        label = hash_name.replace("_", "-").upper() if hash_name else "DEFAULT"

        recursive_hash_item = Nautilus.MenuItem(name=f"{label}_Recursive_{caller}", label=label)
        recursive_hash_item.connect("activate", self.nautilus_launch_app, files, hash_name, True)
        return recursive_hash_item

    def _add_hash_items(self, caller: str, files: list[str], simple_submenu: Nautilus.Menu, recursive_submenu: Nautilus.Menu | None = None) -> None:
        for hash_name in NAUTILUS_CONTEXT_MENU_ALGORITHMS:
            # Hash Simple ()
            simple_hash_item = self._simple_hash_item(caller, hash_name, files)
            # > Hash Simple ()
            simple_submenu.append_item(simple_hash_item)

            if recursive_submenu:
                # Hash Recursive ()
                recursive_hash_item = self._recursive_hash_item(caller, hash_name, files)
                # > Hash Recursive ()
                recursive_submenu.append_item(recursive_hash_item)

    def _simple_submenu(self, caller: str, submenu: Nautilus.Menu) -> Nautilus.Menu:
        """Simple Submenu"""
        simple_menu_item = Nautilus.MenuItem(name=f"Simple_{caller}", label="Simple")
        # Quick > Simple
        submenu.append_item(simple_menu_item)
        # >
        simple_submenu = Nautilus.Menu()
        # Quick > Simple >
        simple_menu_item.set_submenu(simple_submenu)
        return simple_submenu

    def _recursive_submenu(self, caller: str, submenu: Nautilus.Menu) -> Nautilus.Menu:
        """Recursive Submenu"""
        recursive_menu_item = Nautilus.MenuItem(name=f"Recursive_{caller}", label="Recursive")
        # Quick > Recursive
        submenu.append_item(recursive_menu_item)
        # >
        recursive_submenu = Nautilus.Menu()
        # Quick > Recursive >
        recursive_menu_item.set_submenu(recursive_submenu)
        return recursive_submenu

    def _create_menu(self, caller: str, files: list[str], has_dir: bool) -> list[Nautilus.MenuItem]:
        # Quick
        quick_file_hasher_menu = Nautilus.MenuItem(name=f"Menu_{caller}", label=APP_NAME)
        # >
        quick_file_hasher_submenu = Nautilus.Menu()
        # Quick >
        quick_file_hasher_menu.set_submenu(quick_file_hasher_submenu)

        if has_dir:
            # Quick > Simple >
            simple_submenu = self._simple_submenu(caller, quick_file_hasher_submenu)
            # Quick > Recursive >
            recursive_submenu = self._recursive_submenu(caller, quick_file_hasher_submenu)
            # Quick > Recursive/Simple > Hash ()
            self._add_hash_items(caller, files, simple_submenu, recursive_submenu)

        else:
            # Quick > Hash ()
            self._add_hash_items(caller, files, quick_file_hasher_submenu)

        return [quick_file_hasher_menu]

    def _validate_to_string(self, file_objects: list[Nautilus.FileInfo]) -> tuple[bool, list[str]]:
        has_dir = False
        validated_paths = []
        for obj in file_objects:
            if not has_dir and obj.is_directory():
                has_dir = True
            if valid_path := obj.get_location().get_path():
                validated_paths.append(valid_path)
        return has_dir, validated_paths

    def get_background_items(self, current_folder: Nautilus.FileInfo) -> list[Nautilus.MenuItem]:
        if valid_path := current_folder.get_location().get_path():
            return self._create_menu("bg", [valid_path], True)

    def get_file_items(self, files: list[Nautilus.FileInfo]) -> list[Nautilus.MenuItem]:
        has_dir, files = self._validate_to_string(files)
        if not files:
            return
        return self._create_menu("fg", files, has_dir)


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

    def get_algorithm(self) -> str:
        return self.get("algo")

    def get_formatted_params(self) -> tuple[bool, bool, str]:
        return (self.use_relative_paths(), self.use_uppercase_hash(), self.get_output_style())

    def get_output_style(self) -> str:
        return CHECKSUM_FORMATS[self.get_output_style_index()]["style"]

    def get_output_style_index(self) -> int:
        return self.get("output-style")

    def use_uppercase_hash(self) -> bool:
        return self.get("uppercase-hash")

    def use_relative_paths(self) -> bool:
        return self.get("relative-paths")

    def save_errors(self) -> bool:
        return self.get("save-errors")

    def include_time(self) -> bool:
        return self.get("include-time")


class Preferences(Adw.PreferencesWindow, ConfigMixin):
    __gtype_name__ = "Preferences"
    _instance = None
    __gsignals__ = {
        "main-window-signal-handler": (GObject.SignalFlags.RUN_FIRST, None, (str, str, bool)),
        "on-items-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
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
        self.setting_relative_path.connect("notify::active", lambda *_: self._set_example_format_text(*self.get_formatted_params()))
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
        group = Adw.PreferencesGroup()

        name_output_style = "output-style"
        name_uppercase_hash = "uppercase-hash"

        self.setting_uppercase_check_button = Gtk.CheckButton(
            name=name_uppercase_hash,
            label="Uppercase",
            tooltip_text="Check it for uppercase hash value and algorithm",
            margin_end=3,
        )
        self.setting_uppercase_check_button.connect("toggled", lambda _: self._on_format_selected(None, self.setting_uppercase_check_button))

        self.checksum_format_example_text = Adw.ActionRow(css_classes=["background-dark"], title_lines=1, use_markup=True)
        self.checksum_format_example_text.add_prefix(Gtk.Box(hexpand=True))
        self.checksum_format_example_text.add_prefix(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        self.checksum_format_example_text.add_prefix(self.setting_uppercase_check_button)

        output_format_row = Adw.ActionRow(title="Output Format", tooltip_text="Choose checksum output format", title_lines=1)
        output_format_row.add_prefix(Gtk.Image.new_from_icon_name("text-x-generic-symbolic"))

        toggle_group = Gtk.Box(valign=Gtk.Align.CENTER, css_classes=["linked"])
        output_format_row.add_suffix(toggle_group)

        self.setting_checksum_format_toggle_group: list[Gtk.ToggleButton] = []

        first_toggle = None
        for fmt in CHECKSUM_FORMATS:
            toggle = Gtk.ToggleButton(name=name_output_style, label=fmt["name"], tooltip_text=fmt["description"], css_classes=["custom-toggle-btn"])
            toggle.connect("toggled", self._on_format_selected, None)

            if first_toggle is None:
                first_toggle = toggle
            else:
                toggle.set_group(first_toggle)

            toggle_group.append(toggle)
            self.setting_checksum_format_toggle_group.append(toggle)

        self._setting_widgets[name_uppercase_hash] = self.setting_uppercase_check_button
        self._setting_widgets[name_output_style] = self.setting_checksum_format_toggle_group

        group.add(output_format_row)
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

                elif isinstance(widget, Gtk.CheckButton):
                    widget.set_active(value)

                elif isinstance(widget, list):
                    if 0 <= value < len(widget):
                        toggle: Gtk.ToggleButton = widget[value]
                        toggle.set_active(True)
                else:
                    self.logger.debug(f"{widget.get_name()}, {type(widget)} failed.")
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

    def _set_example_format_text(self, use_relative_paths: bool, use_uppercase_hash: bool, output_style: str) -> None:
        example_file = "example.txt" if use_relative_paths else "/folder/example.txt"
        example_hash = "FDFBA9FC68" if use_uppercase_hash else "fdfba9fc68"
        example_algo = "SHA256" if use_uppercase_hash else "sha256"

        example_text = output_style.format(hash=example_hash, filename=example_file, algo=example_algo)
        self.checksum_format_example_text.set_title(f'<span letter_spacing="1200">{example_text}</span>')

    def _on_format_selected(self, button_output_style: Gtk.ToggleButton | None, button_uppercase: Gtk.CheckButton | None) -> None:
        if button_output_style:
            config_key_for_output_style = button_output_style.get_name()
            new_value = self.setting_checksum_format_toggle_group.index(button_output_style)
            self.update(config_key_for_output_style, new_value)

        if button_uppercase:
            config_key_for_uppercase_hash = button_uppercase.get_name()
            new_value = button_uppercase.get_active()
            uppercase_hash_updated = self.update(config_key_for_uppercase_hash, new_value)

            if uppercase_hash_updated:
                self.emit("main-window-signal-handler", "call-row-data", "set_attr_uppercase_result", new_value)

        self._set_example_format_text(*self.get_formatted_params())

    def _on_switch_row_changed(self, switch_row: Adw.SwitchRow, param: GObject.ParamSpec) -> None:
        new_value = switch_row.get_active()
        config_key = switch_row.get_name()
        success = self.update(config_key, new_value)
        if success:
            if config_key == "save-errors":
                self.emit("on-items-changed", None)

            elif config_key == "relative-paths":
                self.emit("main-window-signal-handler", "call-row-data", "set_attr_relative_path", new_value)

    def _on_spin_row_changed(self, spin_row: Adw.SpinRow, param: GObject.ParamSpec) -> None:
        new_value = int(spin_row.get_value())
        config_key = spin_row.get_name()
        self.update(config_key, new_value)

    def _on_algo_selected(self, algo: Adw.ComboRow, param: GObject.ParamSpec) -> None:
        selected_hashing_algorithm = algo.get_selected_item().get_string()
        config_key = algo.get_name()
        self.update(config_key, selected_hashing_algorithm)


class ChecksumRow:
    _logger = get_logger("ChecksumRow")
    patterns = [
        ("bsd", re.compile(r"^([\w-]+)\s+\((.+)\)\s*=\s*([A-Fa-f0-9]{8,128})$")),
        ("colon3", re.compile(r"^(.*)\s*:\s*([A-Fa-f0-9]{8,128})\s*:\s*(.*)$")),
        ("colon2", re.compile(r"^(.*)\s*:\s*([A-Fa-f0-9]{8,128})$")),
        ("gnu", re.compile(r"^([A-Fa-f0-9]{8,128})\s+[* ]?(.*\S)$")),
    ]

    def __init__(self, path: Path, hash_value: str, algo: str | None, line_no: int):
        self.path = path
        self.hash_value = hash_value
        self.algo = algo
        self.line_no = line_no

    def __hash__(self) -> int:
        return hash((self.path.name, self.hash_value))

    def __eq__(self, other: "ResultRowData") -> bool:
        return self.path.name == other.path.name and self.hash_value == other.hash_value

    def __repr__(self) -> str:
        return f"ChecksumRow(filename={self.path!r}, hash={self.hash_value!r}, algo={self.algo!r})"

    def get_key(self) -> tuple[str, str]:
        return (self.path.name, self.hash_value)

    @staticmethod
    def parser(lines: list[str]):
        checksum_rows: dict[tuple[str, str], ChecksumRow] = {}
        errors: list[ErrorRowData] = []
        for line_no, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith(";") or line.startswith("#"):
                continue

            for name, pat in ChecksumRow.patterns:
                if m := pat.match(line):
                    if name == "bsd":
                        algo, filename, hash_value = m.groups()

                    elif name == "colon3":
                        filename, hash_value, algo = m.groups()

                    elif name == "colon2":
                        filename, hash_value = m.groups()
                        algo = None

                    elif name == "gnu":
                        hash_value, filename = m.groups()
                        algo = None

                    row = ChecksumRow(
                        Path(filename.strip()),
                        hash_value.strip().lower(),
                        algo.strip().lower() if algo else None,
                        line_no,
                    )
                    checksum_rows[row.get_key()] = row
                    break
            else:
                path = Path("Checksum row")
                msg = f"Unexpected line at {line_no}: {line}"
                errors.append(ErrorRowData(path, path, msg))
                ChecksumRow._logger.debug(msg)

        return (checksum_rows, errors)

    @staticmethod
    def parse_checksum_file(file_path: Path, callback: Callable[[dict[tuple[str, str], "ChecksumRow"]], None]) -> None:
        with file_path.open() as f:
            lines = f.read().splitlines()
        checksum_rows, errors = ChecksumRow.parser(lines)
        GLib.idle_add(callback, checksum_rows, errors)

    @staticmethod
    def parse_string(content: str, callback: Callable[[dict[tuple[str, str], "ChecksumRow"]], None]) -> None:
        checksum_rows, errors = ChecksumRow.parser(content.splitlines())
        GLib.idle_add(callback, checksum_rows, errors)


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

    def update_error(self, base_path: Path, file: Path, error: str) -> None:
        self.q.put(("error", base_path, file, error))

    def update_toast(self, message: str) -> None:
        self.q.put(("toast", message))

    def get_update(self):
        return self.q.get_nowait()

    def is_empty(self) -> bool:
        return self.q.empty()

    def reset(self) -> None:
        self.q = Queue()


class CalculateHashes:
    def __init__(self, queue: QueueUpdateHandler, cancel_event: threading.Event):
        self.logger = get_logger(self.__class__.__name__)
        self.queue_handler = queue
        self.cancel_event = cancel_event
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
                    self.queue_handler.update_error(base_path, path, "File or directory not found")
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
                self.queue_handler.update_error(base_path, path, str(e))

        if not jobs["sizes"]:
            self.queue_handler.update_progress(1)
            self.queue_handler.update_toast("❌ Zero bytes. No files were hashed.")

        return jobs

    def _process_path_n_rules(self, base_path: Path, current_path: Path, current_rules: list[IgnoreRule], jobs: dict[str, list], options: dict) -> None:
        if self.cancel_event.is_set():
            return
        try:
            if current_path.is_symlink():
                self.queue_handler.update_error(base_path, current_path, "Symbolic links are not supported")
                self.logger.debug(f"Skipped symbolic link: {current_path}")

            elif IgnoreRule.is_ignored(current_path, current_rules):
                self.logger.debug(f"Skipped late: {current_path}")

            elif current_path.is_file():
                file_size = current_path.stat().st_size

                if file_size == 0:
                    if not options.get("ignore-empty-files"):
                        self.queue_handler.update_error(base_path, current_path, "File is empty")

                else:
                    self._total_bytes += file_size
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
            self.queue_handler.update_error(base_path, current_path, str(e))

    def _update_progress(self) -> float:
        if self._total_bytes > 0:
            p = min(self._total_bytes_read / self._total_bytes, 1.0)
        else:
            p = 1.0
        self.queue_handler.update_progress(p)

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
                    hash_obj.update(chunk)
                    bytes_read = len(chunk)
                    hash_task_bytes_read += bytes_read
                    self._add_bytes_read(bytes_read)
                    if self.cancel_event.is_set():
                        return
                    self._update_progress()

            hash_value = hash_obj.hexdigest(shake_length) if "shake" in algorithm else hash_obj.hexdigest()
            self.queue_handler.update_result(base_path, file, hash_value, algorithm)

        except Exception as e:
            self._add_bytes_read(file_size - hash_task_bytes_read)
            self._update_progress()
            self.queue_handler.update_error(base_path, file, str(e))
            self.logger.exception(f"Error processing {file.name}: {e}", stack_info=True)

    def _add_bytes_read(self, bytes_: int):
        self._total_bytes_read += bytes_

    def reset_counters(self) -> None:
        self._total_bytes_read = 0
        self._total_bytes = 0


class RowData(GObject.Object):
    __gtype_name__ = "RowData"
    _use_relative_path: bool = False
    _use_uppercase_result: bool = False
    noop_copy: bool = False
    noop_cmp: bool = False
    _model: str = None

    def __init__(self, base_path: Path, path: Path, **kwargs):
        super().__init__(**kwargs)
        self.base_path = base_path
        self.path = path
        self.rel_path = self._get_rel_path()

    def get_prefix(self) -> str:
        raise NotImplementedError("Subclasses must implement this method")

    def get_result(self) -> str:
        raise NotImplementedError("Subclasses must implement this method")

    def get_search_fields(self, lower: bool = False) -> tuple[Any]:
        raise NotImplementedError("Subclasses must implement this method")

    def get_formatted(self, use_relative_path: bool, use_uppercase_result: bool, output_style: str | None) -> str:
        raise NotImplementedError("Subclasses must implement this method")

    @GObject.Property(type=str)
    def prop_path(self) -> str:
        if self._use_relative_path:
            return GLib.markup_escape_text(self.rel_path)
        return GLib.markup_escape_text(self.path.as_posix())

    @GObject.Property(type=str)
    def prop_result(self) -> str:
        if self._use_uppercase_result:
            return GLib.markup_escape_text(self.get_result().upper())
        return GLib.markup_escape_text(self.get_result())

    def set_attr_relative_path(self, state: bool) -> None:
        if self._use_relative_path != state:
            self._use_relative_path = state
            self.notify("prop_path")

    def set_attr_uppercase_result(self, state: bool) -> None:
        if self._use_uppercase_result != state:
            self._use_uppercase_result = state
            self.notify("prop_result")

    def _get_rel_path(self):
        base_str = self.base_path.as_posix()
        path_str = self.path.as_posix()
        return f"{self.base_path.name}{path_str[len(base_str) :]}"

    def signal_handler(self, emitter: Any, method: str, new_value: bool) -> None:
        getattr(self, method)(new_value)


class ResultRowData(RowData):
    __gtype_name__ = "ResultRowData"
    _model = "results_model"
    # -1 for new row, 0 eq no match and >0 is a match
    line_no: int = GObject.Property(type=int, default=-1)

    def __init__(self, base_path: Path, path: Path, hash_value: str, algo: str, **kwargs):
        super().__init__(base_path, path, **kwargs)
        self.hash_value = hash_value
        self.algo = algo

    def __hash__(self):
        return hash((self.path.name, self.hash_value))

    def __eq__(self, other: ChecksumRow) -> bool:
        return self.path.name == other.path.name and self.hash_value == other.hash_value

    def __repr__(self) -> str:
        return f"ResultRowData(path={self.path!r}, hash={self.hash_value!r}, algo={self.algo!r})"

    def get_prefix(self):
        return self.algo.upper().replace("_", "-")

    def get_result(self) -> str:
        return self.hash_value

    def get_formatted(self, use_relative_path: bool, use_uppercase_hash: bool, output_style: str) -> str:
        filename = self.rel_path if use_relative_path else self.path.as_posix()
        hash_value = self.hash_value.upper() if use_uppercase_hash else self.hash_value
        algo = self.algo.upper() if use_uppercase_hash else self.algo
        return output_style.format(hash=hash_value, filename=filename, algo=algo)

    def get_search_fields(self, lower: bool = False) -> tuple[str, str, str]:
        path_str = self.path.as_posix().lower() if lower else self.path.as_posix()
        return (path_str, self.hash_value, self.algo)

    def get_key(self):
        return (self.path.name, self.hash_value)


class ErrorRowData(RowData):
    __gtype_name__ = "ErrorRowData"
    _model = "errors_model"

    def __init__(self, base_path: Path, path: Path, error_message: str, **kwargs):
        super().__init__(base_path, path, **kwargs)
        self._error_message = error_message

    def __hash__(self):
        return hash((self.path.name, self._error_message))

    def get_prefix(self):
        return "ERROR"

    def get_result(self):
        return self._error_message

    def get_formatted(self, use_relative_path: bool, use_uppercase_error_message: bool, output_style=None) -> str:
        filename = self.rel_path if use_relative_path else self.path.as_posix()
        error_message = self._error_message.upper() if use_uppercase_error_message else self._error_message
        return f"{filename} -> {error_message}"

    def get_search_fields(self, lower: bool = False) -> tuple[str, str]:
        if lower:
            return (self.path.as_posix().lower(), self._error_message.lower())
        return (self.path.as_posix(), self._error_message)


class WidgetHashRow(Gtk.Box):
    __gtype_name__ = "WidgetHashRow"
    _btn_css: str | None = None
    button_copy: Gtk.Button
    button_delete: Gtk.Button

    def __init__(self, **kwargs):
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            css_classes=["background-light", "rounded-medium", "padding-large", "custom-glow"],
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

    def bind(self, row_data: RowData, list_item: Gtk.ListItem, model: Gio.ListStore, parent: "MainWindow") -> None:
        self.prefix_label.set_text(row_data.get_prefix())
        list_item.path_to_title_binding = row_data.bind_property("prop_path", self.title, "label", GObject.BindingFlags.SYNC_CREATE)
        list_item.result_to_subtitle_binding = row_data.bind_property("prop_result", self.subtitle, "label", GObject.BindingFlags.SYNC_CREATE)
        list_item.row_data_signal_handler_id = parent.connect("call-row-data", row_data.signal_handler)

        if not isinstance(self, WidgetChecksumResultRow):
            list_item.copy_handler_id = self.button_copy.connect("clicked", parent.on_copy_row_requested, row_data, self._btn_css)
            list_item.delete_handler_id = self.button_delete.connect("clicked", parent.on_delete_row_requested, self, row_data, model)
            self.button_delete.set_sensitive(True)

        row_data.set_attr_relative_path(parent.pref.use_relative_paths())
        row_data.set_attr_uppercase_result(parent.pref.use_uppercase_hash())

    def unbind(self, row_data: RowData, list_item: Gtk.ListItem, parent: "MainWindow") -> None:
        list_item.path_to_title_binding.unbind()
        list_item.path_to_title_binding = None
        list_item.result_to_subtitle_binding.unbind()
        list_item.result_to_subtitle_binding = None
        parent.disconnect(list_item.row_data_signal_handler_id)

        if not isinstance(self, WidgetChecksumResultRow):
            self.button_copy.disconnect(list_item.copy_handler_id)
            if hasattr(list_item, "delete_handler_id") and list_item.delete_handler_id > 0:
                self.button_delete.disconnect(list_item.delete_handler_id)
                list_item.delete_handler_id = 0
            self.button_delete.set_sensitive(False)


class WidgetHashResultRow(WidgetHashRow):
    __gtype_name__ = "WidgetHashResultRow"
    _icon_name = "dialog-password-symbolic"
    _btn_css = "success"

    def __init__(self):
        super().__init__()
        self.prefix_icon.set_from_icon_name(self._icon_name)
        self.button_multi_hash = self._create_button(None, "Select and compute multiple hash algorithms for this file", None)
        self.button_multi_hash.set_child(Gtk.Label(label="Multi-Hash"))
        self.button_copy = self._create_button("edit-copy-symbolic", "Copy hash", None)
        self.button_compare = self._create_button("edit-paste-symbolic", "Compare with clipboard", None)
        self.button_delete = self._create_button("user-trash-symbolic", "Remove this result", None)

    def set_icon_(self, icon_name: Literal["text-x-generic-symbolic", "object-select-symbolic", "dialog-error-symbolic"]):
        self.prefix_icon.set_from_icon_name(icon_name)

    def reset_icon(self) -> None:
        self.set_icon_(self._icon_name)

    def reset_css(self) -> None:
        self.remove_css_class("custom-success")
        self.remove_css_class("custom-error")

    def bind(self, row_data: ResultRowData, list_item: Gtk.ListItem, model: Gio.ListStore, parent: "MainWindow") -> None:
        super().bind(row_data, list_item, model, parent)
        list_item.multi_hash_handler_id = self.button_multi_hash.connect("clicked", parent.on_multi_hash_requested, row_data)
        list_item.compare_handler_id = self.button_compare.connect("clicked", parent.on_clipboard_compare_requested, self, row_data)

    def unbind(self, row_data: ResultRowData, list_item: Gtk.ListItem, parent: "MainWindow") -> None:
        super().unbind(row_data, list_item, parent)
        self.button_multi_hash.disconnect(list_item.multi_hash_handler_id)
        self.button_compare.disconnect(list_item.compare_handler_id)


class WidgetChecksumResultRow(WidgetHashRow):
    __gtype_name__ = "WidgetChecksumResultRow"
    _icon_name = "dialog-password-symbolic"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.prefix_icon.set_from_icon_name(self._icon_name)
        self.remove(self.suffix_box)
        self.suffix_label = Gtk.Label(valign=Gtk.Align.CENTER, margin_end=4)
        self.append(self.suffix_label)

    def on_match_changed(self, row_data: ResultRowData, _):
        if row_data.line_no == -1:
            self.remove_css_class("custom-success")
            self.remove_css_class("custom-error")
            self.suffix_label.set_text("")
            self._set_label_state(None)
            self.prefix_icon.set_from_icon_name(self._icon_name)
        elif row_data.line_no > 0:
            self.suffix_label.set_text(f"Matched line {row_data.line_no}")
            self._set_label_state("success")
            self.prefix_icon.set_from_icon_name("object-select-symbolic")
        else:
            self.suffix_label.set_text("No match found")
            self._set_label_state("error")
            self.prefix_icon.set_from_icon_name("dialog-error-symbolic")

    def _set_label_state(self, state: str | None):
        for cls in ("custom-success", "custom-error"):
            self.suffix_label.remove_css_class(cls)
            self.prefix_icon.remove_css_class(cls)

        if state == "success":
            self.suffix_label.add_css_class("custom-success")
            self.prefix_icon.add_css_class("custom-success")
        elif state == "error":
            self.suffix_label.add_css_class("custom-error")
            self.prefix_icon.add_css_class("custom-error")

    def bind(self, row_data, list_item, model, parent):
        super().bind(row_data, list_item, model, parent)
        list_item.notify_binding = row_data.connect("notify::line-no", self.on_match_changed)
        self.on_match_changed(row_data, None)

    def unbind(self, row_data, list_item, parent):
        super().unbind(row_data, list_item, parent)
        row_data.disconnect(list_item.notify_binding)


class WidgetHashErrorRow(WidgetHashRow):
    __gtype_name__ = "WidgetHashErrorRow"
    _icon_name = "dialog-error-symbolic"
    _btn_css = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.prefix_icon.set_from_icon_name(self._icon_name)

        self.button_copy = self._create_button("edit-copy-symbolic", "Copy error message", None)
        self.button_delete = self._create_button("user-trash-symbolic", "Remove this error", None)
        self.add_css_class("custom-error")

    def bind(self, row_data: ErrorRowData, list_item: Gtk.ListItem, model: Gio.ListStore, parent: "MainWindow") -> None:
        super().bind(row_data, list_item, model, parent)

    def unbind(self, row_data: ErrorRowData, list_item: Gtk.ListItem, parent: "MainWindow") -> None:
        super().unbind(row_data, list_item, parent)


class SearchProvider(Gtk.Button):
    SEARCH_OPTIONS = [
        ("case-sensitive", "Case Sensitive", "Make search case sensitive"),
        ("exact-match", "Exact Match", "Match the exact search term"),
        ("hide-checksum-matches", "Hide Matches", "Hide results that match loaded checksums"),
    ]

    def __init__(self):
        super().__init__(icon_name="edit-find-symbolic", tooltip_text="Open Search Bar (Ctrl+F)")
        self.set_sensitive(False)
        self.logger = get_logger(self.__class__.__name__)

        self._search_options: dict[str, bool] = {}
        self._search_terms: list[str] = []
        self._view_stack: Adw.ViewStack | None = None
        self._filters: dict[str, Gtk.Filter] = {}

        self.connect("clicked", lambda _: self.show_search_bar(not self.get_search_bar().is_visible()))
        self._setup_search()

    def toggle_option(self, name: str) -> None:
        if opt := self._setting_search_option_widgets.get(name):
            opt.set_active(not opt.get_active())
            self.logger.debug(f"Search option '{name}' toggled to '{opt.get_active()}'")
        else:
            self.logger.debug(f"Search option '{name}' not found")

    def get_search_bar(self) -> Gtk.Box:
        return self._content

    def _setup_search(self) -> None:
        self._content = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            css_classes=["background-light", "rounded-medium", "border-small"],
            valign=Gtk.Align.END,
            spacing=6,
            margin_start=10,
            margin_end=10,
            margin_bottom=20,
            visible=False,
        )
        self._search_entry = Gtk.SearchEntry(
            placeholder_text="Type to filter results (ESC to clear)",
            hexpand=True,
            search_delay=500,
            css_classes=["background-light"],
        )
        options_box = self._create_options_box()

        self._content.append(self._search_entry)
        self._content.append(options_box)

    def _create_options_box(self) -> Gtk.Box:
        options_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, margin_end=8)

        self._setting_search_option_widgets: dict[str, Gtk.CheckButton] = {}

        for name, label, tooltip_text in self.SEARCH_OPTIONS:
            checkbutton = Gtk.CheckButton(name=name, label=label, tooltip_text=tooltip_text)
            checkbutton.connect("toggled", self._on_option_toggled)
            options_box.append(checkbutton)
            self._setting_search_option_widgets[name] = checkbutton

        return options_box

    def complete_setup(self, view_stack: Adw.ViewStack, filters: dict[str, Gtk.Filter]) -> None:
        self._view_stack = view_stack
        self._filters = filters
        self._connect_search_to_view()
        view_stack.connect("notify::visible-child", self._connect_search_to_view)

    def show_search_bar(self, show: bool) -> None:
        if not self.is_sensitive():
            self.get_root().add_toast("🔍 No Results. Search is unavailable.")
            return

        self.get_search_bar().set_visible(show)

        if show:
            self._search_entry.grab_focus()
        else:
            self._search_entry.set_text("")

    def _on_option_toggled(self, button: Gtk.CheckButton) -> None:
        key = button.get_name()
        new_value = button.get_active()
        self._search_options[key] = new_value
        self._search_entry.emit("search-changed")

        self.logger.debug(f"Search option '{key}' toggled to '{new_value}'")

    def _connect_search_to_view(self, _view_stack: Adw.ViewStack = None, _param: GObject.ParamSpecString = None) -> None:
        if hasattr(self._search_entry, "current_search_handler_id"):
            self._search_entry.disconnect(self._search_entry.current_search_handler_id)

        current_page_name = self._view_stack.get_visible_child_name()
        custom_filter = self._filters.get(current_page_name)
        self._search_entry.current_search_handler_id = self._search_entry.connect("search-changed", self._on_search_changed, custom_filter)
        self.logger.debug(f"Search connected to '{current_page_name}'")

    def _on_search_changed(self, entry: Gtk.SearchEntry, custom_filter: Gtk.Filter) -> None:
        if self._search_options.get("case-sensitive"):
            search_text = entry.get_text()
        else:
            search_text = entry.get_text().lower()

        if self._search_options.get("exact-match"):
            self._search_terms = [search_text]
        else:
            self._search_terms = search_text.split()

        custom_filter.changed(Gtk.FilterChange.DIFFERENT)

    def _has_match(self, row: RowData) -> bool:
        if not self._search_terms:
            return True

        fields = row.get_search_fields(lower=not self._search_options.get("case-sensitive"))

        if self._search_options.get("exact-match"):
            return any(self._search_terms[0] in field for field in fields)

        return all(any(term in field for field in fields) for term in self._search_terms)

    def results_filter_func(self, row: "ResultRowData") -> bool:
        """Filter function for results."""
        if row.line_no > 0 and self._search_options.get("hide-checksum-matches"):
            return False
        return self._has_match(row)

    def errors_filter_func(self, row: "ErrorRowData") -> bool:
        """Filter function for errors."""
        return self._has_match(row)


class CompareBanner(Gtk.Revealer):
    def __init__(self):
        super().__init__(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN, transition_duration=300, hexpand=True)
        self.main_grid = Gtk.Grid(
            margin_bottom=8,
            hexpand=True,
            column_homogeneous=True,
            css_classes=["padding-small", "custom-banner-theme", "rounded-bottom", "rounded-top-small"],
        )

        self.prefix = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, halign=Gtk.Align.START, valign=Gtk.Align.CENTER)
        self.content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, spacing=4)
        self.suffix = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, halign=Gtk.Align.END, valign=Gtk.Align.CENTER)

        self.main_grid.attach(self.prefix, 0, 0, 1, 1)
        self.main_grid.attach(self.content, 1, 0, 1, 1)
        self.main_grid.attach(self.suffix, 2, 0, 1, 1)

        self.content_label = Gtk.Label(xalign=0)
        self.content.append(self.content_label)

        button_close = Gtk.Button.new_from_icon_name("window-close-symbolic")
        button_close.add_css_class("flat")
        button_close.set_tooltip_text("Dismiss")
        button_close.set_valign(Gtk.Align.CENTER)
        button_close.connect("clicked", lambda _: self.close())
        self.suffix.append(button_close)

        self.prefix.set_size_request(-1, 32)
        self.content.set_size_request(-1, 32)
        self.suffix.set_size_request(-1, 32)

        self.set_child(self.main_grid)

    def add_prefix(self, widget: Gtk.Widget) -> None:
        widget.set_valign(Gtk.Align.CENTER)
        self.prefix.append(widget)

    def show_results(self, matches: int, no_matches: int) -> None:
        self.content_label.set_text(f"✔ Match: {matches:<10} ✖ No Match: {no_matches}")
        self.set_reveal_child(True)

    def close(self):
        self.set_reveal_child(False)


class MultiHashDialog(Adw.AlertDialog):
    def __init__(self, parent: "MainWindow", row_data: ResultRowData, working_config: dict, **kwargs):
        super().__init__(**kwargs)
        heading = "Select Additional Algorithms"
        body = "<small>Choose one or more algorithms to run in addition to the calculated one.</small>"
        self.set_heading(heading)
        self.set_body(body)
        self.set_body_use_markup(True)
        self.add_response("cancel", "Cancel")
        self.add_response("compute", "Compute")
        self.set_response_appearance("compute", Adw.ResponseAppearance.SUGGESTED)
        self.set_response_enabled("compute", False)
        self.set_close_response("cancel")

        vertical_main_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=5)
        self.set_extra_child(vertical_main_container)

        display_row = WidgetHashRow()
        display_row.remove(display_row.prefix_label)
        display_row.prefix_icon.set_from_icon_name("folder-documents-symbolic")
        display_row.add_css_class("background-dark")
        display_row.remove_css_class("custom-glow")
        display_row.title.set_text(row_data.path.name)
        display_row.subtitle.set_text(f"{row_data.get_prefix()}  {row_data.prop_result}")
        display_row.set_margin_bottom(8)
        vertical_main_container.append(display_row)

        horizontal_container_check_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        vertical_main_container.append(horizontal_container_check_buttons)

        horizontal_container_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, halign=Gtk.Align.END, spacing=6, margin_top=10)
        vertical_main_container.append(horizontal_container_buttons)

        select_all_button = Gtk.Button(label="Select All", css_classes=["flat"])
        horizontal_container_buttons.append(select_all_button)

        unselect_all_button = Gtk.Button(label="Unselect All", css_classes=["flat"])
        horizontal_container_buttons.append(unselect_all_button)

        check_buttons: list[Gtk.CheckButton] = []
        can_compute = lambda *_: self.set_response_enabled("compute", any(c.get_active() for c in check_buttons))
        on_button_click = lambda _, state: list(c.set_active(state) for c in check_buttons)

        count = 0
        for algo in AVAILABLE_ALGORITHMS:
            if algo == row_data.algo:
                continue

            if count % 5 == 0:
                current_check_box_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, hexpand=True, halign=Gtk.Align.CENTER)
                horizontal_container_check_buttons.append(current_check_box_container)

            check_button = Gtk.CheckButton(label=algo.replace("_", "-").upper())
            check_button.algo = algo
            check_button.connect("notify::active", can_compute)

            check_buttons.append(check_button)
            current_check_box_container.append(check_button)
            count += 1

        select_all_button.connect("clicked", on_button_click, True)
        unselect_all_button.connect("clicked", on_button_click, False)

        def on_response(_, response_id):
            if response_id == "compute":
                selected_algos = [c.algo for c in check_buttons if c.get_active()]
                repeat_n_times = len(selected_algos)
                parent.start_job(
                    repeat(row_data.base_path, repeat_n_times),
                    repeat(row_data.path, repeat_n_times),
                    selected_algos,
                    working_config,
                )

        self.connect("response", on_response)
        self.present(parent)


class MainWindow(Adw.ApplicationWindow):
    __gtype_name__ = "MainWindow"
    DEFAULT_WIDTH = 970
    DEFAULT_HEIGHT = 650
    __gsignals__ = {"call-row-data": (GObject.SignalFlags.RUN_FIRST, None, (str, bool))}

    def __init__(self, app: "QuickFileHasher"):
        super().__init__(application=app, title=APP_NAME)
        self.set_default_size(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)

        self.logger = get_logger(self.__class__.__name__)
        self.app = app
        self.pref = app.pref

        self._pref_on_items_changed_id = self.pref.connect("on-items-changed", self.on_items_changed)
        self._pref_main_window_signal_id = self.pref.connect("main-window-signal-handler", self.signal_handler)
        self.connect("close-request", self._on_close_request)

        self.checksum_rows: dict[tuple[str, str], "ChecksumRow"] = {}
        self.rows_selected: list[ResultRowData] = []

        self.cancel_event = threading.Event()
        self.job_in_progress = threading.Event()

        self.queue_handler = QueueUpdateHandler()
        self._calculate_hashes = CalculateHashes(self.queue_handler, self.cancel_event)

        self._build_ui()
        self._create_actions()

    def signal_handler(self, emitter: Any, signal: str, method: str, new_value: bool) -> None:
        self.emit(signal, method, new_value)

    def _build_ui(self) -> None:
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        self.overlay = Gtk.Overlay()
        self.toast_overlay.set_child(self.overlay)

        self.search_provider = SearchProvider()
        self.overlay.add_overlay(self.search_provider.get_search_bar())

        self._setup_drag_and_drop()
        self.overlay.add_overlay(self.dnd_revealer)

        self.toolbar_view = Adw.ToolbarView(margin_top=6, margin_bottom=6, margin_start=12, margin_end=12)
        self.overlay.set_child(self.toolbar_view)

        self._setup_top_bar()
        self.toolbar_view.add_top_bar(self.top_bar_box)

        self.view_switcher = Adw.ViewSwitcher(
            halign=Gtk.Align.CENTER,
            policy=Adw.ViewSwitcherPolicy.WIDE,
            css_classes=["view-switcher"],
            margin_bottom=6,
        )
        self.toolbar_view.add_top_bar(self.view_switcher)

        self._setup_content()
        self.toolbar_view.set_content(self.content_overlay)

        self.progress_bar = Gtk.ProgressBar(opacity=0, margin_top=2)
        self.toolbar_view.add_bottom_bar(self.progress_bar)

    def _setup_drag_and_drop(self) -> None:
        dnd_status_page = Adw.StatusPage(
            title="Drop Files Here",
            icon_name="document-send-symbolic",
            css_classes=["dnd-overlay"],
        )
        self.dnd_revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.CROSSFADE,
            reveal_child=False,
            can_target=False,
            child=dnd_status_page,
        )

        drop = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop.connect("enter", lambda *_: (self.dnd_revealer.set_reveal_child(True), Gdk.DragAction.COPY)[1])
        drop.connect("leave", lambda *_: self.dnd_revealer.set_reveal_child(False))

        def on_drop(ctrl, drop: Gdk.FileList, x, y) -> bool:
            try:
                files = [Path(file.get_path()) for file in drop.get_files()]
                self.start_job(None, files, repeat(self.pref.get_algorithm()), self.pref.get_working_config())
                return True
            except Exception as e:
                self.add_toast(f"Drag & Drop failed: {e}")
                return False
            finally:
                self.dnd_revealer.set_reveal_child(False)

        drop.connect("drop", on_drop)
        self.add_controller(drop)

    def _setup_top_bar(self) -> None:
        self.top_bar_box = Gtk.CenterBox(orientation=Gtk.Orientation.HORIZONTAL, margin_bottom=10)

        button_box = Gtk.Box(spacing=6, css_classes=["toolbar"])

        self.button_cancel_job = Gtk.Button(sensitive=False)
        self.button_cancel_job.set_child(Adw.ButtonContent(icon_name="process-stop-symbolic", label="Cancel Job", tooltip_text="Cancel an ongoing job"))
        self.button_cancel_job.add_css_class("destructive-action")
        self.button_cancel_job.connect("clicked", lambda _: (self.cancel_event.set(), self.add_toast("❌ Job Cancelled")))

        self.button_select_files = Gtk.Button()
        self.button_select_files.set_child(Adw.ButtonContent(icon_name="document-open-symbolic", label="Select Files", tooltip_text="Select files for compute"))
        self.button_select_files.connect("clicked", self._on_select_files_or_folders_clicked, True)

        self.button_select_folders = Gtk.Button()
        self.button_select_folders.set_child(Adw.ButtonContent(icon_name="folder-symbolic", label="Select Folders", tooltip_text="Select folder contents for compute"))
        self.button_select_folders.connect("clicked", self._on_select_files_or_folders_clicked, False)

        self.button_save_to_file = Gtk.Button(sensitive=False)
        self.button_save_to_file.set_child(Adw.ButtonContent(icon_name="document-save-symbolic", label="Save", tooltip_text="Save results to file"))
        self.button_save_to_file.connect("clicked", self._on_save_clicked)

        button_box.append(self.button_cancel_job)
        button_box.append(self.button_select_files)
        button_box.append(self.button_select_folders)
        button_box.append(self.button_save_to_file)

        self.header_bar = Adw.HeaderBar(title_widget=Gtk.Label(label=f"<big><b>{APP_NAME}</b></big>", use_markup=True))
        self._setup_menu()

        self.top_bar_box.set_start_widget(button_box)
        self.top_bar_box.set_end_widget(self.header_bar)

    def _setup_factory(self, obj: WidgetHashRow):
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup, obj)
        factory.connect("bind", self._on_factory_bind)
        factory.connect("unbind", self._on_factory_unbind)
        factory.connect("teardown", self._on_factory_teardown)
        return factory

    def _setup_scrolled_window(self, list_view: Gtk.ListView):
        return Gtk.ScrolledWindow(child=list_view, hscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vscrollbar_policy=Gtk.PolicyType.AUTOMATIC, hexpand=True, vexpand=True)

    def _setup_results_view(self) -> None:
        self.results_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, css_classes=["toolbar"], halign=Gtk.Align.CENTER)

        self.results_model = Gio.ListStore.new(ResultRowData)
        self.results_model.connect("items-changed", self._on_items_changed)

        self.results_custom_sorter = Gtk.CustomSorter.new(self._sort_by_hierarchy, None)
        results_model_sorted = Gtk.SortListModel.new(self.results_model, self.results_custom_sorter)

        self.results_custom_filter = Gtk.CustomFilter.new(self.search_provider.results_filter_func)
        self.results_model_filtered = Gtk.FilterListModel.new(results_model_sorted, self.results_custom_filter)

        results_model_selection = Gtk.NoSelection.new(self.results_model_filtered)

        factory = self._setup_factory(WidgetHashResultRow)
        results_list_view = Gtk.ListView(model=results_model_selection, factory=factory, css_classes=["no-background", "rich-list"])

        self.results_scrolled_window = self._setup_scrolled_window(results_list_view)

        self.button_copy_all = Gtk.Button(sensitive=False)
        self.button_copy_all.set_child(Adw.ButtonContent(icon_name="edit-copy-symbolic", label="Copy to clipboard", tooltip_text="Copy all results to clipboard"))
        self.button_copy_all.connect("clicked", self._on_copy_all_clicked)

        self.toggle_button_sort = Gtk.ToggleButton(tooltip_text="Sort results by path", css_classes=["custom-toggle-btn"], sensitive=False, valign=Gtk.Align.CENTER)
        self.toggle_button_sort.set_child(Adw.ButtonContent(icon_name="media-playlist-shuffle-symbolic", label="Sort", tooltip_text="Sort results by path hierarchy"))
        self.toggle_button_sort.connect("toggled", self._on_sort_toggled)

        self.button_clear = Gtk.Button(sensitive=False)
        self.button_clear.set_child(Adw.ButtonContent(icon_name="edit-clear-all-symbolic", label="Clear results", tooltip_text="Clear all results and errors"))
        self.button_clear.connect("clicked", self._on_clear_clicked)

        button_row.append(self.button_copy_all)
        button_row.append(self.toggle_button_sort)
        button_row.append(self.button_clear)

        self.results_container.append(button_row)
        self.results_container.append(self.results_scrolled_window)

    def _setup_checksum_results_view(self) -> None:
        self.checksum_results_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, css_classes=["toolbar"], halign=Gtk.Align.CENTER)

        checksum_results_selection_model = Gtk.MultiSelection.new(self.results_model_filtered)
        checksum_results_selection_model.connect("selection-changed", self._on_checksum_selection_changed)

        factory = self._setup_factory(WidgetChecksumResultRow)
        checksum_results_list_view = Gtk.ListView(model=checksum_results_selection_model, factory=factory, css_classes=["no-background", "rich-list"])

        checksum_results_scrolled_window = self._setup_scrolled_window(checksum_results_list_view)

        self.button_checksum_compare = Gtk.Button(sensitive=False)
        self.button_checksum_compare.set_child(Adw.ButtonContent(icon_name="object-select-symbolic", label="Compare"))
        self.button_checksum_compare.set_tooltip_text("Compare your generated hashes against the loaded checksum file/clipboard")
        self.button_checksum_compare.connect("clicked", lambda _: threading.Thread(target=self._on_checksum_compare_file_or_clipboard, daemon=True).start())

        button_checksum_file_upload = Gtk.Button()
        button_checksum_file_upload.set_child(Adw.ButtonContent(icon_name="document-open-symbolic", label="Load Checksum File"))
        button_checksum_file_upload.set_tooltip_text("Select a checksum file to compare against your results")
        button_checksum_file_upload.connect("clicked", self._on_checksum_file_upload)

        button_checksum_paste_clipboard = Gtk.Button()
        button_checksum_paste_clipboard.set_child(Adw.ButtonContent(icon_name="edit-copy-symbolic", label="Paste Clipboard"))
        button_checksum_paste_clipboard.set_tooltip_text("Paste checksums from the clipboard and compare them with your results")
        button_checksum_paste_clipboard.connect("clicked", self._on_checksum_paste_clipboard)

        button_select_all = Gtk.Button()
        button_select_all.set_child(Adw.ButtonContent(icon_name="edit-select-all-symbolic", label="Select All"))
        button_select_all.connect("clicked", lambda _: checksum_results_selection_model.select_all())

        button_unselect_all = Gtk.Button()
        button_unselect_all.set_child(Adw.ButtonContent(icon_name="edit-clear-all-symbolic", label="Unselect All"))
        button_unselect_all.connect("clicked", lambda _: checksum_results_selection_model.unselect_all())

        self.button_checksum_reset = Gtk.Button()
        self.button_checksum_reset.set_child(Adw.ButtonContent(icon_name="edit-undo-symbolic", label="Reset"))
        self.button_checksum_reset.connect("clicked", self._on_checksum_results_reset_request, checksum_results_selection_model)

        self.checksum_banner_compare = CompareBanner()
        button_hide_matches = Gtk.Button(css_classes=["flat", "rounded-top-small", "rounded-bottom"])
        button_hide_matches.set_child(Adw.ButtonContent(icon_name="edit-find-symbolic", label="Toggle Hide Matches", tooltip_text=self.search_provider.SEARCH_OPTIONS[2][2]))
        button_hide_matches.connect("clicked", lambda _: self.search_provider.toggle_option("hide-checksum-matches"))
        self.checksum_banner_compare.add_prefix(button_hide_matches)

        button_row.append(self.button_checksum_compare)
        button_row.append(button_checksum_paste_clipboard)
        button_row.append(button_checksum_file_upload)
        button_row.append(button_select_all)
        button_row.append(button_unselect_all)
        button_row.append(self.button_checksum_reset)

        self.checksum_results_container.append(button_row)
        self.checksum_results_container.append(self.checksum_banner_compare)
        self.checksum_results_container.append(checksum_results_scrolled_window)

    def _setup_errors_view(self) -> None:
        self.errors_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        self.errors_model = Gio.ListStore.new(ErrorRowData)
        self.errors_model.connect("items-changed", self._on_items_changed)

        self.errors_custom_filter = Gtk.CustomFilter.new(self.search_provider.errors_filter_func)
        self.errors_model_filtered = Gtk.FilterListModel.new(self.errors_model, self.errors_custom_filter)

        errors_selection_model = Gtk.NoSelection(model=self.errors_model_filtered)

        factory = self._setup_factory(WidgetHashErrorRow)
        errors_list_view = Gtk.ListView(model=errors_selection_model, factory=factory, css_classes=["no-background", "rich-list"])

        errors_scrolled_window = self._setup_scrolled_window(errors_list_view)
        self.errors_container.append(errors_scrolled_window)

    def _setup_content(self) -> None:
        self.content_overlay = Gtk.Overlay()

        self.clamp = Adw.Clamp()
        self.empty_placeholder = Adw.StatusPage(title="No Results", description="Select files or folders to calculate their hashes.", icon_name="text-x-generic-symbolic")

        self.view_stack = Adw.ViewStack(visible=False)
        self.view_switcher.set_stack(self.view_stack)
        self.clamp.set_child(self.view_stack)

        self.content_overlay.set_child(self.clamp)
        self.content_overlay.add_overlay(self.empty_placeholder)

        self._setup_results_view()
        self.results_stack_page = self.view_stack.add_titled_with_icon(self.results_container, "results", "Results", "view-list-symbolic")
        self._setup_checksum_results_view()
        self.checksum_results_stack_page = self.view_stack.add_titled_with_icon(self.checksum_results_container, "checksum-results", "Checksum", "object-select-symbolic")
        self._setup_errors_view()
        self.errors_stack_page = self.view_stack.add_titled_with_icon(self.errors_container, "errors", "Errors", "dialog-error-symbolic")

        filters = {
            "checksum-results": self.results_custom_filter,
            "results": self.results_custom_filter,
            "errors": self.errors_custom_filter,
        }
        self.search_provider.complete_setup(self.view_stack, filters)

        self.view_stack.connect("notify::visible-child", self.on_items_changed)

    def _setup_menu(self) -> None:
        menu = Gio.Menu()
        menu.append("Preferences", "app.preferences")
        menu.append("Copy to Clipboard", "win.results-copy")
        menu.append("Keyboard Shortcuts", "app.shortcuts")
        menu.append("About", "app.about")
        menu.append("Quit", "win.quit")
        button_menu = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        self.header_bar.pack_end(button_menu)
        self.header_bar.pack_end(self.search_provider)

    def _modify_placeholder(self, current_page_name: str) -> bool:
        if current_page_name == "results":
            title = "No Results"
            icon_name = "text-x-generic-symbolic"
            description = "Select files or folders to calculate their hashes."
        elif current_page_name == "errors":
            title = "No Errors"
            icon_name = "object-select-symbolic"
            description = " "
        else:
            title = "Nothing to verify"
            icon_name = "view-list-symbolic"
            description = " "
        current_title = self.empty_placeholder.get_title()
        if current_title == title:
            return False
        self.empty_placeholder.set_title(title)
        self.empty_placeholder.set_icon_name(icon_name)
        self.empty_placeholder.set_description(description)
        return True

    def _sort_by_hierarchy(self, row1: ResultRowData, row2: ResultRowData, _) -> int:
        """
        - /folder/a.txt
        - /folder/z.txt
        - /folder/subfolder_b/
        - /folder/subfolder_b/file.txt
        - /folder/subfolder_y/
        """
        if not self.toggle_button_sort.get_active():
            return 0

        p1, p2 = row1.path, row2.path

        if p1.parent.parts != p2.parent.parts:
            return -1 if p1.parent.parts < p2.parent.parts else 1

        if p1.name != p2.name:
            return -1 if p1.name < p2.name else 1
        return 0

    def _timeout_add(self, interval: int, callback: Callable[..., bool], *args):
        interval_seconds = interval / 1000

        def loop():
            while True:
                keep_going = callback(*args)
                if not keep_going:
                    break
                time.sleep(interval_seconds)

        threading.Thread(target=loop, daemon=True).start()

    def start_job(
        self,
        base_paths: Iterable[Path] | None,
        paths: Iterable[Path],
        hashing_algorithms: Iterable[str],
        options: dict,
    ) -> None:
        self.cancel_event.clear()
        if self.job_in_progress.is_set():
            self.logger.debug("Job in progress… starting shortly.")
            self._timeout_add(500, self._pending_job, base_paths, paths, hashing_algorithms, options)
            return

        self.job_in_progress.set()
        self.button_cancel_job.set_sensitive(True)
        self.progress_bar.set_opacity(1.0)

        threading.Thread(
            target=self._calculate_hashes,
            args=(base_paths or paths, paths, hashing_algorithms, options),
            daemon=True,
        ).start()

        self._timeout_add(10, self._process_queue)

    def _pending_job(self, *args):
        if self.job_in_progress.is_set():
            return True
        GLib.idle_add(self.start_job, *args)
        return False

    def _process_queue(self) -> bool:
        queue_empty = self.queue_handler.is_empty()
        job_done = self.progress_bar.get_fraction() == 1.0
        canceled = self.cancel_event.is_set()

        if canceled or (queue_empty and job_done):
            GLib.idle_add(self._processing_complete)
            return False

        new_rows = []
        new_errors = []
        additions = 0
        while additions < 500:
            try:
                update = self.queue_handler.get_update()
            except Empty:
                break

            kind = update[0]
            if kind == "progress":
                GLib.idle_add(self.progress_bar.set_fraction, update[1])

            elif kind == "result":
                additions += 1
                new_rows.append(ResultRowData(*update[1:]))

            elif kind == "error":
                additions += 1
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
        self.queue_handler.reset()
        self.button_cancel_job.set_sensitive(False)
        self._calculate_hashes.reset_counters()

        def done(_):
            self.progress_bar.set_fraction(0.0)
            self._scroll_to_bottom()
            self.job_in_progress.clear()

        anim_target = Adw.CallbackAnimationTarget.new(lambda opacity: self.progress_bar.set_opacity(opacity))
        anim = Adw.TimedAnimation.new(self, 1.0, 0.0, 250, anim_target)
        anim.connect("done", done)
        anim.play()

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
            duration=500,
            target=Adw.CallbackAnimationTarget.new(lambda value: vadjustment.set_value(value)),
        ).play()

    def _txt_to_file(self, output: bytes | None) -> None:
        if output is None:
            self.add_toast("❌ Nothing to save")
            return
        file_dialog = Gtk.FileDialog(title="Save", initial_name="results.txt")

        def on_file_dialog_dismissed(file_dialog: Gtk.FileDialog, gio_task: Gio.Task) -> None:
            if not gio_task.had_error():
                try:
                    local_file = file_dialog.save_finish(gio_task)
                    path: str = local_file.get_path()

                    with open(path, "wb") as f:
                        f.write(output)

                    self.add_toast("✅ Saved")

                except Exception as e:
                    self.logger.error(f"Unexcepted error occured for '{path}': '{e}'")
                    self.add_toast(f"❌ Failed: {e}")

        file_dialog.save(parent=self, callback=on_file_dialog_dismissed)

    def _txt_to_clipboard(self, output: bytes | None):
        if output:
            cp = Gdk.ContentProvider.new_for_bytes("text/plain;charset=utf-8", GLib.Bytes.new(output))
            self.get_clipboard().set_content(cp)
            toast = "✅ Results copied to clipboard"
        else:
            toast = "❌ Nothing to copy"
        self.add_toast(toast)

    def _results_to_txt(self, callback: Callable[[bytes | None], None]) -> None:
        def worker():
            parts = []
            total_results = self.results_model_filtered.get_n_items()
            total_errors = self.errors_model_filtered.get_n_items()
            formatted_params = self.pref.get_formatted_params()

            if total_results > 0:
                results_txt = "\n".join(r.get_formatted(*formatted_params) for r in self.results_model_filtered)
                parts.append(f"# Results ({total_results}):\n\n{results_txt}")

            if self.pref.save_errors() and total_errors > 0:
                errors_txt = "\n".join(r.get_formatted(*formatted_params) for r in self.errors_model_filtered)
                parts.append(f"# Errors ({total_errors}):\n\n{errors_txt}")

            if self.pref.include_time() and parts:
                now = datetime.now().astimezone().strftime("%B %d, %Y at %H:%M:%S %Z")
                parts.append(f"# Generated on {now}")

            if parts:
                output = "\n\n".join(parts).encode("utf-8")
            else:
                output = None

            GLib.idle_add(callback, output)

        threading.Thread(target=worker, daemon=True).start()

    def _on_factory_setup(self, factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem, obj: WidgetHashRow) -> None:
        row_widget = obj()
        selectable = isinstance(row_widget, WidgetChecksumResultRow)
        list_item.set_selectable(selectable)
        list_item.set_activatable(False)
        list_item.set_focusable(False)
        list_item.set_child(row_widget)

    def _on_factory_bind(self, factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        row_widget: WidgetHashRow = list_item.get_child()
        row_data: RowData = list_item.get_item()
        model = getattr(self, row_data._model)
        row_widget.bind(row_data, list_item, model, self)

    def _on_factory_unbind(self, factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        row_widget: WidgetHashRow = list_item.get_child()
        row_data: RowData = list_item.get_item()
        row_widget.unbind(row_data, list_item, self)

    def _on_factory_teardown(self, factory: Gtk.SignalListItemFactory, list_item: Gtk.ListItem) -> None:
        list_item.set_child(None)

    def _on_items_changed(self, model: Gio.ListStore, position: int, removed: int, added: int) -> None:
        self.on_items_changed()

    def on_items_changed(self, view_stack: Adw.ViewStack = None, param: GObject.ParamSpec = None) -> None:
        current_page_name = self.view_stack.get_visible_child_name()

        has_results = self.results_model.get_n_items() > 0
        has_errors = self.errors_model.get_n_items() > 0
        save_errors = self.pref.save_errors()

        has_selected_rows = len(self.rows_selected) > 0
        has_checksum_rows = len(self.checksum_rows) > 0

        self.button_checksum_compare.set_sensitive(has_selected_rows and has_checksum_rows)
        self.button_checksum_reset.set_sensitive(has_checksum_rows)

        can_save_or_copy = has_results or (has_errors and save_errors)
        can_clear_or_search = has_results or has_errors
        self.button_save_to_file.set_sensitive(can_save_or_copy)
        self.button_copy_all.set_sensitive(can_save_or_copy)
        self.toggle_button_sort.set_sensitive(has_results)
        self.button_clear.set_sensitive(can_clear_or_search)
        self.search_provider.set_sensitive(can_clear_or_search)

        self._update_badge_numbers()

        show_empty = (current_page_name in ("results", "checksum-results") and not has_results) or (current_page_name == "errors" and not has_errors)

        if show_empty:
            self._modify_placeholder(current_page_name)
            target = self.empty_placeholder
        else:
            target = self.view_stack

        if target.is_visible() and not (view_stack and param):
            return

        anim_target = Adw.CallbackAnimationTarget.new(lambda opacity: target.set_opacity(opacity))
        anim = Adw.TimedAnimation(widget=self, value_from=0.4, value_to=1.0, duration=250, target=anim_target)
        anim.play()
        self.view_stack.set_visible(not show_empty)
        self.empty_placeholder.set_visible(show_empty)

    def checksum_add_rows(self, checksum_rows: dict[tuple[str, str], "ChecksumRow"] | None, errors: list[ErrorRowData] | None):
        """Callback"""
        if checksum_rows:
            toast = "✅ Success"
            self.checksum_rows = checksum_rows
        else:
            self.checksum_rows.clear()

        if errors:
            toast = "❌ Something went wrong. Check 'Errors' view."
            self.errors_model.splice(self.errors_model.get_n_items(), 0, errors)

        self.add_toast(toast)
        self.on_items_changed()

    def _on_checksum_results_reset_request(self, button: Gtk.Button, selection_model: Gtk.MultiSelection):
        selection_model.select_all()
        self.checksum_rows.clear()
        self.checksum_banner_compare.close()
        self.add_toast("✅ Reset")
        for row_data in self.rows_selected:
            row_data.line_no = -1
        selection_model.unselect_all()

    def _on_checksum_compare_file_or_clipboard(self) -> None:
        matches = 0
        no_matches = 0

        def set_row_data_line_no(row_data: ResultRowData, line_no: int):
            row_data.line_no = line_no

        for row_data in self.rows_selected:
            if checksum_row := self.checksum_rows.get(row_data.get_key()):
                GLib.idle_add(set_row_data_line_no, row_data, checksum_row.line_no)
                matches += 1
            else:
                GLib.idle_add(set_row_data_line_no, row_data, 0)
                no_matches += 1

        GLib.idle_add(self.checksum_banner_compare.show_results, matches, no_matches)

    def _on_checksum_file_upload(self, _: Gtk.Button) -> None:
        file_dialog = Gtk.FileDialog(title="Select File")
        text_filter = Gtk.FileFilter(name="Plain Text File", mime_types=["text/plain"])
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(text_filter)
        file_dialog.set_filters(filters)
        file_dialog.set_default_filter(text_filter)

        def on_files_dialog_dismissed(file_dialog: Gtk.FileDialog, gio_task: Gio.Task) -> None:
            if not gio_task.had_error():
                file: Gio.File = file_dialog.open_finish(gio_task)
                path = Path(file.get_path())
                threading.Thread(target=ChecksumRow.parse_checksum_file, args=(path, self.checksum_add_rows), daemon=True).start()

        file_dialog.open(parent=self, callback=on_files_dialog_dismissed)

    def _on_checksum_paste_clipboard(self, button: Gtk.Button) -> None:
        def handle_clipboard_comparison(clipboard: Gdk.Clipboard, result):
            try:
                clipboard_text = clipboard.read_text_finish(result).strip()
                threading.Thread(target=ChecksumRow.parse_string, args=(clipboard_text, self.checksum_add_rows), daemon=True).start()
            except Exception as e:
                self.add_toast(f"Clipboard read failed: {e}")

        clipboard = button.get_clipboard()
        clipboard.read_text_async(None, handle_clipboard_comparison)

    def _on_checksum_selection_changed(self, selection_model: Gtk.MultiSelection, position: int, n_items: int) -> None:
        self.rows_selected: list[ResultRowData] = []
        model = selection_model.get_model()

        bitset: Gtk.Bitset = selection_model.get_selection()
        if bitset.is_empty():
            self.on_items_changed()
            return

        valid, iter_, index = Gtk.BitsetIter.init_first(bitset)

        while valid:
            item: ResultRowData = model.get_item(index)
            self.rows_selected.append(item)
            valid, index = iter_.next()

        self.on_items_changed()

    def on_multi_hash_requested(self, _: Gtk.Button, row: ResultRowData) -> None:
        MultiHashDialog(self, row, self.pref.get_working_config())

    def on_copy_row_requested(self, button: Gtk.Button, row_data: RowData, css: str | None = None) -> None:
        if row_data.noop_copy:
            return
        row_data.noop_copy = True
        button.get_clipboard().set(row_data.get_result())
        icon_name = button.get_icon_name()
        button.set_icon_name("object-select-symbolic")

        if css:
            button.add_css_class(css)

        def reset():
            button.set_icon_name(icon_name)
            button.remove_css_class("success")
            row_data.noop_copy = False

        GLib.timeout_add(1500, reset)

    def on_clipboard_compare_requested(self, _: Gtk.Button, row_widget: WidgetHashResultRow, row_data: ResultRowData) -> None:
        if row_data.noop_cmp:
            return
        row_data.noop_cmp = True

        def handle_clipboard_comparison(clipboard: Gdk.Clipboard, result):
            try:
                clipboard_text: str = clipboard.read_text_finish(result).strip()

                if clipboard_text.lower() == row_data.get_result():
                    row_widget.add_css_class("custom-success")
                    row_widget.set_icon_("object-select-symbolic")
                    self.add_toast(f"✅ Clipboard hash matches <b>{row_data.prop_path}</b>!")

                else:
                    row_widget.add_css_class("custom-error")
                    row_widget.set_icon_("dialog-error-symbolic")
                    self.add_toast(f"❌ The clipboard hash does not match <b>{row_data.prop_path}</b>!")

            except Exception as e:
                self.add_toast(f"❌ Clipboard read error: {e}")

            finally:

                def reset():
                    row_widget.reset_css()
                    row_widget.reset_icon()
                    row_data.noop_cmp = False

                GLib.timeout_add(3000, reset)

        clipboard = self.get_clipboard()
        clipboard.read_text_async(None, handle_clipboard_comparison)

    def on_delete_row_requested(self, button: Gtk.Button, row_widget: WidgetHashRow, row_data: RowData, model: Gio.ListStore) -> None:
        button.set_sensitive(False)

        found, position = model.find(row_data)
        if not found:
            raise ValueError("Item not found in original model")

        anim = Adw.TimedAnimation(
            widget=row_widget,
            value_from=1.0,
            value_to=0.3,
            duration=100,
            target=Adw.CallbackAnimationTarget.new(lambda opacity: row_widget.set_opacity(opacity)),
        )
        anim.connect("done", lambda _: model.remove(position))
        anim.play()

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
            self.search_provider.show_search_bar(False)
            self.results_model.remove_all()
            self.errors_model.remove_all()
            self.add_toast("✅ Results cleared")

    def _on_sort_toggled(self, toggle: Gtk.ToggleButton) -> None:
        if toggle.get_active():
            self.add_toast("✅ Sort Enabled")
            self.results_custom_sorter.changed(Gtk.FilterChange.DIFFERENT)
        else:
            self.add_toast("❌ Sort Disabled")

    def _on_close_request(self, window: Adw.Window) -> None:
        self.cancel_event.set()
        self.pref.disconnect(self._pref_on_items_changed_id)
        self.pref.disconnect(self._pref_main_window_signal_id)
        self.results_model.remove_all()
        self.errors_model.remove_all()
        self.checksum_rows = None
        self.rows_selected = None
        self.pref = None
        self.app = None

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
            ("show-searchbar", lambda *_: self.search_provider.show_search_bar(True), ["<Ctrl>F"]),
            ("hide-searchbar", lambda *_: self.search_provider.show_search_bar(False), ["Escape"]),
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
            paths = [(Path(cwd) / path).resolve() for path in paths]
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
        main_window.start_job(None, paths, repeat(hash_algorithm), options)
        main_window.present()

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
            application_name=APP_NAME,
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
        self.set_option_context_summary(f"{APP_NAME} - Verify your files with speed and confidence")
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
