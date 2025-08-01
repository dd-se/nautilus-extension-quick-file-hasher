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
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import lru_cache
from itertools import repeat
from pathlib import Path
from queue import Empty, Queue
from typing import Callable, Literal

signal.signal(signal.SIGINT, lambda s, f: exit(print("Interrupted by user (Ctrl+C)")))
os.environ["LANG"] = "en_US.UTF-8"
import gi  # type: ignore

gi.require_version(namespace="Gtk", version="4.0")
gi.require_version(namespace="Adw", version="1")
gi.require_version(namespace="Nautilus", version="4.0")

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Nautilus, Pango  # type: ignore

APP_ID = "com.github.dd-se.quick-file-hasher"
APP_VERSION = "1.0.0"
PRIORITY_ALGORITHMS = ["md5", "sha1", "sha256", "sha512"]
AVAILABLE_ALGORITHMS = PRIORITY_ALGORITHMS + sorted(hashlib.algorithms_available - set(PRIORITY_ALGORITHMS))
NAUTILUS_CONTEXT_MENU_ALGORITHMS = [None] + AVAILABLE_ALGORITHMS
CONFIG_DIR = Path(GLib.get_user_config_dir()) / APP_ID
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULTS = {
    "algo": "sha256",
    "max-visible-results": 100,
    "max-workers": 4,
    "recursive": False,
    "gitignore": False,
    "ignore-empty-files": False,
    "save-errors": False,
    "absolute-paths": True,
    "include-time": True,
}
VIEW_SWITCHER_CSS = b"""
.view-switcher button {
    background-color: #404040;
    color: white;
    transition: background-color 0.5s ease;
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
"""


def get_logger(name: str) -> logging.Logger:
    loglevel_str = os.getenv("LOGLEVEL", "INFO").upper()
    warnings.filterwarnings("ignore" if loglevel_str == "INFO" else "default", category=DeprecationWarning)
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
css_provider = Gtk.CssProvider()
css_provider.load_from_data(VIEW_SWITCHER_CSS)
Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


class AdwNautilusExtension(GObject.GObject, Nautilus.MenuProvider):
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)

    def nautilus_launch_app(
        self,
        menu_item: Nautilus.MenuItem,
        files: list[Nautilus.FileInfo],
        hash_algorithm: str = None,
        recursive_mode: bool = False,
    ):
        self.logger.debug(f"App {APP_ID} launched by file manager")

        cmd = ["python3", __file__] + [f.get_location().get_path() for f in files]
        if hash_algorithm:
            cmd.extend(["--algo", hash_algorithm])

        if recursive_mode:
            cmd.extend(["--recursive", "--gitignore"])

        self.logger.debug(f"With args: {cmd}")
        subprocess.Popen(cmd)

    def create_menu(self, files, caller, PREFIX="OpenInApp"):
        quick_file_hasher_menu = Nautilus.MenuItem(
            name=f"{PREFIX}_Menu_{caller}",
            label="Quick File Hasher",  # Quick
        )
        quick_file_hasher_submenu = Nautilus.Menu()  # >
        quick_file_hasher_menu.set_submenu(quick_file_hasher_submenu)  # Quick >

        if any(f.is_directory() for f in files):
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

    def get_background_items(self, current_folder: Nautilus.FileInfo) -> list[Nautilus.MenuItem]:
        if not current_folder.is_directory():
            return []
        return self.create_menu([current_folder], 1)

    def get_file_items(self, files: list[Nautilus.FileInfo]) -> list[Nautilus.MenuItem]:
        if not files:
            return []
        return self.create_menu(files, 2)


class Preferences(Adw.PreferencesWindow):
    _instance = None
    _notified_of_limit_breach = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, **kwargs):
        if hasattr(self, "_initialized"):
            return
        super().__init__(**kwargs)
        self.set_title("Preferences")
        self.set_modal(True)
        self.set_hide_on_close(True)
        self.set_size_request(0, MainWindow.DEFAULT_HEIGHT - 100)

        self.logger = get_logger(self.__class__.__name__)
        self._setting_widgets: dict[str, Adw.ActionRow] = {}

        self.setup_processing_page()
        self.setup_saving_page()
        self.setup_hashing_page()

        self.load_config_file()
        self.apply_config()
        self.apply_env_variables()

        self.connect("close-request", self.on_close)
        self.setting_save_errors.connect("notify::active", lambda *_: MainWindow().has_results())
        self._initialized = True

    def setup_processing_page(self):
        processing_page = Adw.PreferencesPage(
            title="Processing",
            icon_name="edit-find-symbolic",
        )
        self.add(processing_page)

        processing_group = Adw.PreferencesGroup(
            description="Configure how files and folders are processed",
        )
        processing_page.add(group=processing_group)

        self.setting_recursive = self.create_switch_row("recursive", "edit-find-symbolic", "Recursive Traversal", "Enable to process all files in subdirectories")
        processing_group.add(child=self.setting_recursive)

        self.setting_gitignore = self.create_switch_row("gitignore", "action-unavailable-symbolic", "Respect .gitignore", "Skip files and folders listed in .gitignore file")
        processing_group.add(child=self.setting_gitignore)

        self.setting_ignore_empty_files = self.create_switch_row("ignore-empty-files", "action-unavailable-symbolic", "Ignore Empty Files", "Don't raise errors for empty files")
        processing_group.add(child=self.setting_ignore_empty_files)

        processing_group.add(self.create_buttons())

    def setup_saving_page(self):
        saving_page = Adw.PreferencesPage(title="Saving", icon_name="document-save-symbolic")
        self.add(saving_page)

        saving_group = Adw.PreferencesGroup(description="Configure how results are saved")
        saving_page.add(group=saving_group)

        self.setting_save_errors = self.create_switch_row("save-errors", "dialog-error-symbolic", "Save Errors", "Save errors to results file or clipboard")

        saving_group.add(child=self.setting_save_errors)

        self.setting_abs_path = self.create_switch_row("absolute-paths", "view-list-symbolic", "Absolute Paths", "Include absolute paths in results")
        saving_group.add(child=self.setting_abs_path)

        self.setting_include_time = self.create_switch_row("include-time", "edit-find-symbolic", "Include Timestamp", "Include timestamp in results")
        saving_group.add(child=self.setting_include_time)

        saving_group.add(child=self.create_buttons())

    def setup_hashing_page(self):
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
        self.setting_algorithm.connect("notify::selected", self.on_algo_selected)
        self.add_reset_button(self.setting_algorithm)
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
        self.setting_max_workers.connect("notify::value", self.on_spin_row_changed)
        self.add_reset_button(self.setting_max_workers)
        self._setting_widgets[self.setting_max_workers.get_name()] = self.setting_max_workers
        hashing_group.add(child=self.setting_max_workers)

        hashing_group.add(child=self.create_buttons())

    def create_switch_row(self, name: str, icon_name: str, title: str, subtitle: str) -> Adw.SwitchRow:
        switch_row = Adw.SwitchRow(name=name, title=title, subtitle=subtitle)
        switch_row.add_prefix(Gtk.Image.new_from_icon_name(icon_name))
        switch_row.connect("notify::active", self.on_switch_row_changed)
        self.add_reset_button(switch_row)
        self._setting_widgets[name] = switch_row
        return switch_row

    def add_reset_button(self, row: Adw.ActionRow):
        reset_button = Gtk.Button(
            label="Reset",
            css_classes=["flat"],
            valign=Gtk.Align.CENTER,
            tooltip_markup="<b>Reset</b> to default value",
            icon_name="edit-undo-symbolic",
        )
        key = row.get_name()
        if isinstance(row, Adw.SwitchRow):
            reset_button.connect("clicked", lambda _: row.set_active(DEFAULTS[key]))

        elif isinstance(row, Adw.SpinRow):
            reset_button.connect("clicked", lambda _: row.set_value(DEFAULTS[key]))

        elif isinstance(row, Adw.ComboRow):
            reset_button.connect("clicked", lambda _: row.set_selected(AVAILABLE_ALGORITHMS.index(DEFAULTS[key])))

        row.add_suffix(reset_button)

    def create_buttons(self):
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
        button_save_preferences.connect("clicked", lambda _: self.save_working_config_to_file())
        button_box.append(button_save_preferences)

        button_reset_preferences = Gtk.Button(
            label="Reset",
            tooltip_text="Reset all preferences to default values",
            hexpand=True,
        )
        button_reset_preferences.add_css_class("destructive-action")
        button_reset_preferences.connect("clicked", lambda _: self.reset_preferences())
        button_box.append(button_reset_preferences)
        return main_box

    def get_config_file(self):
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config: dict = json.load(f)
                return config

        except json.JSONDecodeError as e:
            self.logger.error(f"{CONFIG_FILE}: {e}. Using defaults.")
            MainWindow().add_toast(f"Error decoding JSON from {CONFIG_FILE}. Using defaults.", priority=Adw.ToastPriority.HIGH)

        except Exception as e:
            self.logger.error(f"{CONFIG_FILE}: {e}. Using defaults.")
            MainWindow().add_toast(f"Unexpected error loading config from {CONFIG_FILE}. Using defaults.", priority=Adw.ToastPriority.HIGH)

    def load_config_file(self):
        self.persisted_config = DEFAULTS.copy()

        if loaded_config := self.get_config_file():
            self.persisted_config.update(loaded_config)
            self.logger.debug(f"Loaded config from {CONFIG_FILE}")

        self.working_config = self.persisted_config.copy()

    def apply_config(self):
        for key, value in self.working_config.items():
            if widget := self._setting_widgets.get(key):
                if isinstance(widget, Adw.SwitchRow):
                    widget.set_active(value)

                elif isinstance(widget, Adw.SpinRow):
                    widget.set_value(value)

                elif isinstance(widget, Adw.ComboRow):
                    widget.set_selected(AVAILABLE_ALGORITHMS.index(value))

        self.logger.debug("Applied config to UI components")

    def apply_options_ui(self, options: dict):
        self.setting_recursive.set_active(options.get("recursive", False))
        self.setting_gitignore.set_active(options.get("gitignore", False))

        if max_workers := options.get("max-workers"):
            self.setting_max_workers.set_value(max_workers)

        if algo := options.get("algo"):
            self.setting_algorithm.set_selected(AVAILABLE_ALGORITHMS.index(algo))

        else:
            self.setting_algorithm.set_selected(AVAILABLE_ALGORITHMS.index(self.persisted_config.get("algo")))

    def get_working_config(self):
        return self.working_config

    def apply_env_variables(self):
        pass

    def save_working_config_to_file(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.working_config, f, indent=4, sort_keys=True)
                self.persisted_config = self.working_config.copy()

            self.add_toast(Adw.Toast(title="<big>Success!</big>", use_markup=True, timeout=1))
            self.logger.debug(f"Preferences saved to file: {CONFIG_FILE}")

        except Exception as e:
            self.add_toast(Adw.Toast(title=str(e)))
            self.logger.error(f"Error saving preferences to {CONFIG_FILE}: {e}")

    def reset_preferences(self):
        for key, value in DEFAULTS.items():
            if widget := self._setting_widgets.get(key):
                if isinstance(widget, Adw.SwitchRow):
                    widget.set_active(value)

                elif isinstance(widget, Adw.SpinRow):
                    widget.set_value(value)

                elif isinstance(widget, Adw.ComboRow):
                    widget.set_selected(AVAILABLE_ALGORITHMS.index(value))

        self.add_toast(Adw.Toast(title="<big>Reset!</big>", use_markup=True, timeout=1))

    def get_algorithm(self) -> str:
        return self.setting_algorithm.get_selected_item().get_string()

    def save_errors(self):
        return self.setting_save_errors.get_active()

    def include_time(self):
        return self.setting_include_time.get_active()

    def max_rows(self) -> int:
        return self.working_config["max-visible-results"]

    def notified_of_limit_breach(self) -> bool:
        return self._notified_of_limit_breach

    def set_recursive_mode(self, action, param):
        state: bool = param.get_string() == "yes"
        self.setting_gitignore.set_active(state)
        self.setting_recursive.set_active(state)
        self.logger.debug(f"Recursive mode set to {state} via action")

    def set_notified_of_limit_breach(self, state: bool):
        self._notified_of_limit_breach = state

    def on_switch_row_changed(self, switch_row: Adw.SwitchRow, param: GObject.ParamSpec):
        new_value = switch_row.get_active()
        config_key = switch_row.get_name()
        if self.working_config.get(config_key) != new_value:
            self.working_config[config_key] = new_value
            self.logger.info(f"Switch Preference '{config_key}' changed to '{new_value}'")

    def on_spin_row_changed(self, spin_row: Adw.SpinRow, param: GObject.ParamSpec):
        new_value = int(spin_row.get_value())
        config_key = spin_row.get_name()
        if self.working_config.get(config_key) != new_value:
            self.working_config[config_key] = new_value
            self.logger.info(f"Spin Preference '{config_key}' changed to {new_value}")

    def on_algo_selected(self, algo: Adw.ComboRow, g_param_object):
        selected_hashing_algorithm = self.get_algorithm()
        config_key = algo.get_name()
        if self.working_config.get(config_key) != selected_hashing_algorithm:
            self.working_config[config_key] = selected_hashing_algorithm
            self.logger.info(f"Algorithm changed to {selected_hashing_algorithm} for new jobs")

    def on_close(self, _):
        MainWindow().search_entry.grab_focus()


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

        pattern = self.clean_trailing_spaces(pattern)
        pattern = pattern.replace("\\ ", " ")

        self.regex = re.compile(self.to_regex(pattern))
        self.base_path = base_path

    def clean_trailing_spaces(self, pattern: str) -> str:
        while pattern.endswith(" ") and not pattern.endswith("\\ "):
            pattern = pattern[:-1]
        return pattern

    def to_regex(self, pattern: str) -> str:
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
    def get_rel_path(self, path: Path) -> str:
        return path.relative_to(self.base_path).as_posix()

    def match(self, path: Path) -> bool:
        if self.directory_only and path.is_file():
            return False

        rel_path = self.get_rel_path(path)
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
        self.logger = get_logger(self.__class__.__name__)

    def update_progress(self, bytes_read: int, total_bytes: int):
        progress = min(bytes_read / total_bytes, 1.0)
        self.q.put(("progress", progress))

    def update_result(self, file: Path, hash_value: str, algo: str):
        self.q.put(("result", file, hash_value, algo))

    def update_error(self, file: Path, error: str):
        self.q.put(("error", file, error))

    def get_update(self):
        return self.q.get_nowait()

    def is_empty(self):
        return self.q.empty()

    def reset(self):
        self.q = Queue()


class CalculateHashes:
    def __init__(self, queue: QueueUpdateHandler, event: threading.Event):
        self.logger = get_logger(self.__class__.__name__)
        self.queue_handler = queue
        self.cancel_event = event
        self.total_bytes = 0
        self.bytes_read = 0

    def __call__(self, paths: list[Path] | list[Gio.File], hash_algorithm: list | str, options: dict):
        jobs = self.create_jobs(paths, options)
        self.execute_jobs(jobs, hash_algorithm, options)

    def execute_jobs(self, jobs: dict[str, list], hash_algorithms: str | list, options: dict):
        hash_algorithms = repeat(hash_algorithms) if isinstance(hash_algorithms, str) else hash_algorithms
        max_workers = options.get("max-workers")
        with ThreadPoolExecutor(max_workers) as executor:
            self.logger.debug(f"Starting hashing with {max_workers} workers")
            list(executor.map(self.hash_task, jobs["paths"], hash_algorithms, jobs["sizes"]))

    def create_jobs(self, paths: list[Path] | list[Gio.File], options: dict):
        jobs = {"paths": [], "sizes": []}

        for root_path in paths:
            try:
                if issubclass(type(root_path), Gio.File):
                    root_path = Path(root_path.get_path())

                ignore_rules = []

                if root_path.is_dir():
                    if options.get("gitingore"):
                        gitignore_file = root_path / ".gitignore"

                        if gitignore_file.exists():
                            ignore_rules = IgnoreRule.parse_gitignore(gitignore_file)
                            self.logger.debug(f"Added rule early: {gitignore_file} ({len(ignore_rules)})")

                    for sub_path in root_path.iterdir():
                        if IgnoreRule.is_ignored(sub_path, ignore_rules):
                            self.logger.debug(f"Skipped early: {sub_path}")
                            continue
                        self.process_path_n_rules(sub_path, ignore_rules, jobs, options)
                else:
                    self.process_path_n_rules(root_path, ignore_rules, jobs, options)

            except Exception as e:
                self.logger.debug(f"Error processing {root_path.name}: {e}")
                self.queue_handler.update_error(root_path, str(e))

        if self.total_bytes == 0:
            self.queue_handler.update_progress(1, 1)

        return jobs

    def process_path_n_rules(self, current_path: Path, current_rules: list[IgnoreRule], jobs: dict[str, list], options: dict):
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
                    self.add_file_size(file_size)
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
                    self.process_path_n_rules(sub_path, local_rules, jobs, options)

            else:
                current_path.stat()

        except Exception as e:
            self.logger.debug(f"Error processing {current_path.name}: {e}")
            self.queue_handler.update_error(current_path, str(e))

    def hash_task(self, file: Path, algorithm: str, file_size: int | None = None, shake_length: int = 32):
        if self.cancel_event.is_set():
            return
        try:
            file_size = file_size or file.stat().st_size
            if file_size > 1024 * 1024 * 100:
                chunk_size = 1024 * 1024 * 4

            else:
                chunk_size = 1024 * 1024

            hash_obj = hashlib.new(algorithm)
            with open(file, "rb") as f:
                while chunk := f.read(chunk_size):
                    if self.cancel_event.is_set():
                        return

                    hash_obj.update(chunk)
                    self.bytes_read += len(chunk)
                    self.queue_handler.update_progress(self.bytes_read, self.total_bytes)

            hash_value = hash_obj.hexdigest(shake_length) if "shake" in algorithm else hash_obj.hexdigest()
            self.queue_handler.update_result(file, hash_value, algorithm)

        except Exception as e:
            self.logger.debug(f"Error processing {file.name}: {e}")
            self.queue_handler.update_error(file, str(e))

    def add_file_size(self, bytes_: int):
        self.total_bytes += bytes_

    def reset_counters(self):
        self.bytes_read = 0
        self.total_bytes = 0


class HashRow(Adw.ActionRow):
    _counter = 0
    _counter_hidden = 0
    _max_width_label = max(len(algo) for algo in AVAILABLE_ALGORITHMS)

    def __init__(self, path: Path, **kwargs):
        super().__init__(**kwargs)
        self._hidden_result = False
        self.path = path
        self.logger = get_logger(self.__class__.__name__)
        self.increment_counter()

    @classmethod
    def get_counter(cls):
        return cls._counter

    @classmethod
    def increment_counter(cls):
        cls._counter += 1
        return cls._counter

    @classmethod
    def decrement_counter(cls):
        if cls._counter > 0:
            cls._counter -= 1
        return cls._counter

    @classmethod
    def get_counter_hidden(cls):
        return cls._counter_hidden

    @classmethod
    def increment_counter_hidden(cls):
        cls._counter_hidden += 1
        return cls._counter_hidden

    @classmethod
    def decrement_counter_hidden(cls):
        if cls._counter_hidden > 0:
            cls._counter_hidden -= 1
        return cls._counter_hidden

    @classmethod
    def reset_counter(cls):
        cls._counter = 0
        cls._counter_hidden = 0

    def is_hidden_result(self):
        return self._hidden_result

    def set_hidden_result(self, value: bool):
        self._hidden_result = value
        self.set_visible(not value)
        if value:
            self.increment_counter_hidden()
        else:
            self.decrement_counter_hidden()
        return self._hidden_result

    def create_button(self, icon_name: str | None, tooltip_text: str, callback: Callable, *args) -> Gtk.Button:
        if icon_name is None:
            button = Gtk.Button()
        else:
            button = Gtk.Button.new_from_icon_name(icon_name)
        button.set_valign(Gtk.Align.CENTER)
        button.set_tooltip_text(tooltip_text)
        button.connect("clicked", callback, *args)
        return button

    def on_click_delete(self, button: Gtk.Button):
        button.set_sensitive(False)
        parent: list[HashRow] = self.get_parent()
        anim = Adw.TimedAnimation(
            widget=self,
            value_from=1.0,
            value_to=0.5,
            duration=100,
            target=Adw.CallbackAnimationTarget.new(lambda opacity: self.set_opacity(opacity)),
        )

        def on_fade_done(_):
            self.decrement_counter()
            parent.remove(self)

            if self.is_hidden_result():
                self.set_hidden_result(False)
            else:
                for row in parent:
                    if row.is_hidden_result():
                        row.set_hidden_result(False)
                        break

            MainWindow().has_results()

        anim.connect("done", on_fade_done)
        anim.play()

    def on_click_copy(self, button: Gtk.Button, add_css: bool = False):
        button.disconnect_by_func(self.on_click_copy)
        button.get_clipboard().set(self.get_subtitle())
        icon_name = button.get_icon_name()
        button.set_icon_name("object-select-symbolic")
        if add_css:
            button.add_css_class("success")
        GLib.timeout_add(
            1500,
            lambda: (
                button.set_icon_name(icon_name),
                button.remove_css_class("success"),
                button.connect("clicked", self.on_click_copy, add_css),
            ),
        )


class HashResultRow(HashRow):
    def __init__(self, path: Path, hash_value: str, hash_algorithm: str, **kwargs):
        super().__init__(path, **kwargs)
        self.hash_value = hash_value
        self.algo = hash_algorithm

        self.set_title(GLib.markup_escape_text(self.path.as_posix()))
        self.set_subtitle(self.hash_value)
        self.set_subtitle_lines(1)
        self.set_title_lines(1)

        self.prefix_hash_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.prefix_hash_box.set_valign(Gtk.Align.CENTER)
        self.hash_icon = Gtk.Image.new_from_icon_name("dialog-password-symbolic")
        self.hash_icon_name = self.hash_icon.get_icon_name()
        self.prefix_hash_box.append(self.hash_icon)
        self.hash_name = Gtk.Label(label=self.algo.upper(), width_chars=self._max_width_label)
        self.prefix_hash_box.append(self.hash_name)
        self.add_prefix(self.prefix_hash_box)

        self.button_make_hashes = self.create_button(None, "Select and compute multiple hash algorithms for this file", self.on_click_make_hashes)
        self.button_make_hashes.set_child(Gtk.Label(label="Multi-Hash"))
        self.button_copy_hash = self.create_button("edit-copy-symbolic", "Copy hash", self.on_click_copy, True)
        self.button_compare = self.create_button("edit-paste-symbolic", "Compare with clipboard", self.on_click_compare)
        self.button_delete = self.create_button("user-trash-symbolic", "Remove this result", self.on_click_delete)

        self.add_suffix(self.button_make_hashes)
        self.add_suffix(self.button_copy_hash)
        self.add_suffix(self.button_compare)
        self.add_suffix(self.button_delete)

        self.set_hidden_result(self.get_counter() > Preferences().max_rows())

    def __str__(self):
        return f"{self.path if Preferences().setting_abs_path.get_active() else self.path.name}:{self.hash_value}:{self.algo}"

    def on_click_make_hashes(self, button: Gtk.Button):
        dialog = Adw.AlertDialog(body="<big><b>Select Hash Algorithms</b></big>", body_use_markup=True)
        dialog.set_presentation_mode(Adw.DialogPresentationMode.BOTTOM_SHEET)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("compute", "Compute")
        dialog.set_response_appearance("compute", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_response_enabled("compute", False)
        dialog.set_close_response("cancel")

        main_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        dialog.set_extra_child(main_container)

        horizontal_container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        main_container.append(horizontal_container)

        horizontal_container_2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        horizontal_container_2.set_halign(Gtk.Align.END)
        main_container.append(horizontal_container_2)

        select_all_button = Gtk.Button(label="Select All")
        select_all_button.add_css_class("flat")
        horizontal_container_2.append(select_all_button)

        deselect_all_button = Gtk.Button(label="Deselect All")
        deselect_all_button.add_css_class("flat")
        horizontal_container_2.append(deselect_all_button)

        switches: list[tuple[Adw.SwitchRow, str]] = []
        can_compute = lambda *_: dialog.set_response_enabled("compute", any(s.get_active() for s, _ in switches))
        on_button_click = lambda _, state: list(s.set_active(state) for s, _ in switches)

        count = 0
        for algo in AVAILABLE_ALGORITHMS:
            if algo != self.algo:
                if count % 5 == 0:
                    current_list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
                    current_list_box.add_css_class("boxed-list")
                    horizontal_container.append(current_list_box)

                switch = Adw.SwitchRow.new()
                switch.connect("notify::active", can_compute)
                switch.add_prefix(Gtk.Label(label=algo.upper()))
                switch.add_prefix(Gtk.Image.new_from_icon_name("dialog-password-symbolic"))

                switches.append((switch, algo))
                current_list_box.append(switch)
                count += 1

        select_all_button.connect("clicked", on_button_click, True)
        deselect_all_button.connect("clicked", on_button_click, False)

        def on_response(_, response_id):
            if response_id == "compute":
                selected_algos = [algo for switch, algo in switches if switch.get_active()]
                paths = [self.path] * len(selected_algos)
                MainWindow().start_job(paths, selected_algos, Preferences().get_working_config())

        dialog.connect("response", on_response)
        dialog.present(MainWindow())

    def on_click_compare(self, button: Gtk.Button):
        button.disconnect_by_func(self.on_click_compare)

        def handle_clipboard_comparison(clipboard, result):
            try:
                clipboard_text: str = clipboard.read_text_finish(result).strip()

                if clipboard_text == self.hash_value:
                    self.set_icon_("object-select-symbolic")
                    self.set_css_("success")
                    MainWindow().add_toast(f"<big>✅ Clipboard hash matches <b>{self.get_title()}</b>!</big>")

                else:
                    self.set_icon_("dialog-error-symbolic")
                    self.set_css_("error")
                    MainWindow().add_toast(f"<big>❌ The clipboard hash does <b>not</b> match <b>{self.get_title()}</b>!</big>")

            except Exception as e:
                self.logger.exception(f"Error reading clipboard: {e}")
                MainWindow().add_toast(f"<big>❌ Clipboard read error: {e}</big>")

            finally:
                GLib.timeout_add(
                    3000,
                    lambda: (
                        self.reset_css(),
                        self.reset_icon(),
                        button.connect("clicked", self.on_click_compare),
                    ),
                )

        clipboard = button.get_clipboard()
        clipboard.read_text_async(None, handle_clipboard_comparison)

    def set_icon_(self, icon_name: Literal["text-x-generic-symbolic", "object-select-symbolic", "dialog-error-symbolic"]):
        self.hash_icon.set_from_icon_name(icon_name)

    def reset_icon(self):
        self.set_icon_(self.hash_icon_name)

    def set_css_(self, css_class: Literal["success", "error"]):
        self.add_css_class(css_class)

    def reset_css(self):
        self.remove_css_class("success")
        self.remove_css_class("error")


class HashErrorRow(HashRow):
    def __init__(self, path: Path, error_message: str, **kwargs):
        super().__init__(path, **kwargs)
        self.error_message = error_message

        self.set_title(GLib.markup_escape_text(self.path.as_posix()))
        self.set_subtitle(GLib.markup_escape_text(self.error_message))
        self.set_title_lines(1)
        self.set_subtitle_lines(1)

        self.prefix_hash_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.prefix_hash_box.set_valign(Gtk.Align.CENTER)
        self.hash_icon = Gtk.Image.new_from_icon_name("dialog-error-symbolic")
        self.prefix_hash_box.append(self.hash_icon)
        self.add_prefix(self.prefix_hash_box)

        self.button_copy_error = self.create_button("edit-copy-symbolic", "Copy error message", self.on_click_copy)
        self.button_delete = self.create_button("user-trash-symbolic", "Remove this error", self.on_click_delete)
        self.add_suffix(self.button_copy_error)
        self.add_suffix(self.button_delete)
        self.add_css_class("error")

    def __str__(self) -> str:
        return f"{self.path if Preferences().setting_abs_path.get_active() else self.path.name}:ERROR:{self.error_message}"


class MainWindow(Adw.ApplicationWindow):
    DEFAULT_WIDTH = 970
    DEFAULT_HEIGHT = 650
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, app=None):
        if hasattr(self, "_initialized"):
            return
        super().__init__(application=app)
        self.logger = get_logger(self.__class__.__name__)
        self.set_default_size(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        self.set_size_request(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        self.build_ui()
        self._initialized = True

        self.pref = Preferences()
        self.pref.set_transient_for(self)
        self.queue_handler = QueueUpdateHandler()
        self.cancel_event = threading.Event()
        self.calculate_hashes = CalculateHashes(self.queue_handler, self.cancel_event)

    def build_ui(self):
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        self.setup_toolbar_view()
        self.toast_overlay.set_child(self.toolbar_view)

        self.setup_first_top_bar()
        self.toolbar_view.add_top_bar(self.first_top_bar_box)

        self.setup_second_top_bar()
        self.toolbar_view.add_top_bar(self.second_top_bar_box)

        self.setup_main_content()
        self.toolbar_view.set_content(self.empty_placeholder)

        self.setup_progress_bar()
        self.toolbar_view.add_bottom_bar(self.progress_bar)

        self.setup_drag_and_drop()

        self.setup_about_window()

        self.setup_shortcuts()

    def setup_toolbar_view(self):
        self.empty_placeholder = Adw.StatusPage(title="No Results", description="Select files or folders to calculate their hashes.", icon_name="text-x-generic-symbolic")
        self.empty_error_placeholder = Adw.StatusPage(title="No Errors", description=" ", icon_name="object-select-symbolic")
        self.toolbar_view = Adw.ToolbarView(margin_top=6, margin_bottom=6, margin_start=12, margin_end=12)

    def create_button(
        self,
        label: str,
        icon_name: str,
        tooltip_text: str,
        css_class: str,
        callback: Callable,
        *args,
    ) -> Gtk.Button:
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

    def setup_first_top_bar(self):
        self.first_top_bar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, margin_bottom=10)

        self.button_select_files = self.create_button("Select Files", "document-open-symbolic", "Select files to add", "suggested-action", self.on_select_files_clicked)
        self.first_top_bar_box.append(self.button_select_files)

        self.button_select_folders = self.create_button("Select Folders", "folder-open-symbolic", "Select folders to add", "suggested-action", self.on_select_folders_clicked)
        self.first_top_bar_box.append(self.button_select_folders)

        self.button_save = self.create_button("Save", "document-save-symbolic", "Save results to file", "suggested-action", self.on_save_clicked)
        self.button_save.set_sensitive(False)

        self.first_top_bar_box.append(self.button_save)

        callback = lambda _: (self.cancel_event.set(), self.add_toast("<big>❌ Jobs Cancelled</big>"))
        self.button_cancel = self.create_button("Cancel Jobs", None, None, "destructive-action", callback)
        self.button_cancel.set_visible(False)
        self.first_top_bar_box.append(self.button_cancel)

        spacer_0 = Gtk.Box()
        spacer_0.set_hexpand(True)
        self.first_top_bar_box.append(spacer_0)

        self.setup_header_bar()
        self.first_top_bar_box.append(self.header_bar)

    def setup_second_top_bar(self):
        self.second_top_bar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, margin_bottom=10)

        self.view_switcher = Adw.ViewSwitcher(hexpand=True, policy=Adw.ViewSwitcherPolicy.WIDE)
        self.view_switcher.add_css_class("view-switcher")
        self.second_top_bar_box.append(self.view_switcher)

        self.hidden_row_counter = self.create_button("Hidden: 0", "help-about-symbolic", "Number of hidden results. Use search to reveal them.", None, None)
        self.hidden_row_counter.set_visible(False)
        self.second_top_bar_box.append(self.hidden_row_counter)

        spacer_1 = Gtk.Box()
        spacer_1.set_hexpand(True)
        self.second_top_bar_box.append(spacer_1)

        self.button_copy_all = self.create_button("Copy", None, "Copy results to clipboard", "suggested-action", self.on_copy_all_clicked)
        self.button_copy_all.set_sensitive(False)
        self.second_top_bar_box.append(self.button_copy_all)

        self.button_sort = self.create_button("Sort", None, "Sort results by path", None, self.on_sort_clicked)
        self.button_sort.set_sensitive(False)
        self.second_top_bar_box.append(self.button_sort)

        self.button_clear = self.create_button("Clear", None, "Clear all results", "destructive-action", self.on_clear_clicked)
        self.button_clear.set_sensitive(False)
        self.second_top_bar_box.append(self.button_clear)

    def setup_header_bar(self):
        self.header_bar = Adw.HeaderBar(
            title_widget=Gtk.Label(label="<big><b>Quick File Hasher</b></big>", use_markup=True),
        )
        self.setup_menu()
        self.setup_search()

    def setup_main_content(self):
        self.main_content_overlay = Gtk.Overlay()

        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.main_content_overlay.add_overlay(self.main_box)

        self.view_stack = Adw.ViewStack(vexpand=True, hexpand=True)
        self.view_switcher.set_stack(self.view_stack)

        self.results_group = Adw.PreferencesGroup(hexpand=True, vexpand=True)

        self.ui_results = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.ui_results.add_css_class("boxed-list")
        self.ui_results.set_filter_func(self.filter_func)
        self.results_group.add(self.ui_results)

        self.results_scrolled_window = Gtk.ScrolledWindow()
        self.results_scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.results_scrolled_window.set_child(self.results_group)

        self.results_stack_page = self.view_stack.add_titled_with_icon(self.results_scrolled_window, "results", "Results", "view-list-symbolic")

        self.errors_group = Adw.PreferencesGroup(hexpand=True, vexpand=True)

        self.ui_errors = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.ui_errors.add_css_class("boxed-list")
        self.ui_errors.set_filter_func(self.filter_func_err)
        self.errors_group.add(self.ui_errors)

        self.errors_scrolled_window = Gtk.ScrolledWindow()
        self.errors_scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.errors_scrolled_window.set_child(self.errors_group)

        self.errors_stack_page = self.view_stack.add_titled_with_icon(self.errors_scrolled_window, "errors", "Errors", "dialog-error-symbolic")

        self.view_stack.set_visible_child_name("results")
        self.view_stack.connect("notify::visible-child", self.has_results)
        self.main_box.append(self.view_stack)

        self.search_entry = Gtk.SearchEntry(placeholder_text="Type to filter & ESC to clear", margin_bottom=2, visible=False)
        for ui_list in (self.ui_results, self.ui_errors):
            self.search_entry.connect("search-changed", self.on_search_changed, ui_list)
        self.search_query = ""
        self.main_box.append(self.search_entry)

    def setup_menu(self):
        menu = Gio.Menu()
        menu.append("Preferences", "app.preferences")
        menu.append("Keyboard Shortcuts", "app.shortcuts")
        menu.append("About", "app.about")
        menu.append("Quit", "app.quit")
        button_menu = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        self.header_bar.pack_end(button_menu)

    def setup_search(self):
        self.button_show_searchbar = Gtk.ToggleButton(
            tooltip_text="Show search bar to filter results and errors",
            sensitive=False,
            icon_name="system-search-symbolic",
        )
        self.button_show_searchbar.connect("clicked", self.on_click_show_searchbar)
        self.header_bar.pack_end(self.button_show_searchbar)

    def setup_shortcuts(self):
        shortcuts = [
            {
                "title": "File Operations",
                "shortcuts": [
                    {"title": "Open Files", "accelerator": "<Ctrl>O"},
                    {"title": "Save Results", "accelerator": "<Ctrl>S"},
                    {"title": "Quit Application", "accelerator": "<Ctrl>Q"},
                ],
            },
            {
                "title": "View & Search",
                "shortcuts": [
                    {"title": "Search Results", "accelerator": "<Ctrl>F"},
                    {"title": "Hide Searchbar", "accelerator": "Escape"},
                    {"title": "Sort Results", "accelerator": "<Ctrl>R"},
                    {"title": "Clear Results", "accelerator": "<Ctrl>L"},
                ],
            },
            {
                "title": "Clipboard",
                "shortcuts": [
                    {"title": "Copy All Results", "accelerator": "<Ctrl>C"},
                ],
            },
        ]

        self.shortcuts_window = Gtk.ShortcutsWindow(modal=True, transient_for=self, hide_on_close=True)

        shortcuts_section = Gtk.ShortcutsSection(section_name="shortcuts", max_height=12)

        for group in shortcuts:
            shortcuts_group = Gtk.ShortcutsGroup(title=group["title"])

            for shortcut in group["shortcuts"]:
                shortcuts_group.add_shortcut(Gtk.ShortcutsShortcut(title=shortcut["title"], accelerator=shortcut["accelerator"]))

            shortcuts_section.add_group(shortcuts_group)

        self.shortcuts_window.add_section(shortcuts_section)

    def setup_progress_bar(self):
        self.progress_bar = Gtk.ProgressBar(opacity=0)

    def setup_drag_and_drop(self):
        self.dnd = Adw.StatusPage(
            title="Drop Files Here",
            icon_name="folder-open-symbolic",
        )
        self.drop = Gtk.DropTargetAsync.new(None, Gdk.DragAction.COPY)
        self.drop.connect("drag-enter", lambda *_: (self.toolbar_view.set_content(self.dnd), Gdk.DragAction.COPY)[1])
        self.drop.connect("drag-leave", lambda *_: (self.has_results(), Gdk.DragAction.COPY)[1])

        def on_read_value(drop: Gdk.Drop, result):
            try:
                files: Gdk.FileList = drop.read_value_finish(result)
                action = Gdk.DragAction.COPY
            except Exception as e:
                action = 0
                self.add_toast(f"Drag & Drop failed: {e}")
            else:
                self.start_job(files, self.pref.get_algorithm(), self.pref.get_working_config())
            finally:
                drop.finish(action)

        self.drop.connect(
            "drop",
            lambda ctrl, drop, x, y: (
                self.has_results(),
                drop.read_value_async(
                    Gdk.FileList,
                    GLib.PRIORITY_DEFAULT,
                    None,
                    on_read_value,
                ),
            ),
        )
        self.add_controller(self.drop)

    def setup_about_window(self):
        self.about_window = Adw.AboutWindow(
            modal=True,
            hide_on_close=True,
            transient_for=self,
            application_name="Quick File Hasher",
            application_icon="document-properties",
            version=APP_VERSION,
            developer_name="Doğukan Doğru (dd-se)",
            license_type=Gtk.License(Gtk.License.MIT_X11),
            comments="A modern Nautilus extension and standalone GTK4/libadwaita app to calculate hashes.",
            website="https://github.com/dd-se/nautilus-extension-quick-file-hasher",
            issue_url="https://github.com/dd-se/nautilus-extension-quick-file-hasher/issues",
            copyright="© 2025 Doğukan Doğru (dd-se)",
            developers=["dd-se https://github.com/dd-se"],
            designers=["dd-se https://github.com/dd-se"],
        )

    def sort_by_hierarchy(self, row1: HashResultRow, row2: HashResultRow) -> int:
        """
        - /folder/a.txt
        - /folder/z.txt
        - /folder/subfolder_b/
        - /folder/subfolder_b/file.txt
        - /folder/subfolder_y/
        """
        p1, p2 = row1.path, row2.path

        if p1.parent.parts != p2.parent.parts:
            return -1 if p1.parent.parts < p2.parent.parts else 1

        if p1.name != p2.name:
            return -1 if p1.name < p2.name else 1
        return 0

    def start_job(self, paths: list[Path] | list[Gio.File], hashing_algorithm: str | list, options: dict):
        self.cancel_event.clear()
        self.button_cancel.set_visible(True)

        self.processing_thread = threading.Thread(
            target=self.calculate_hashes,
            args=(paths, hashing_algorithm, options),
            daemon=True,
        )
        self.processing_thread.start()
        GLib.timeout_add(500, self.first_result, priority=GLib.PRIORITY_DEFAULT_IDLE)
        GLib.timeout_add(50, self.process_queue, priority=GLib.PRIORITY_DEFAULT_IDLE)

    def first_result(self):
        if not (HashResultRow.get_counter() > 0 or HashErrorRow.get_counter() > 0):
            return True
        self.has_results()

    def process_queue(self):
        self.progress_bar.set_opacity(1.0)

        queue_empty = self.queue_handler.is_empty()
        job_done = self.progress_bar.get_fraction() == 1.0

        if self.cancel_event.is_set() or (queue_empty and job_done):
            self.processing_complete()
            return False

        iterations = 0
        while iterations < 100:
            try:
                update = self.queue_handler.get_update()
            except Empty:
                break

            kind = update[0]
            if kind == "progress":
                self.progress_bar.set_fraction(update[1])

            elif kind == "result":
                iterations += 1
                GLib.timeout_add(250, self.ui_results.append, HashResultRow(*update[1:]))

            elif kind == "error":
                iterations += 1
                GLib.timeout_add(250, self.ui_errors.append, HashErrorRow(*update[1:]))

        return True  # Continue monitoring

    def processing_complete(self):
        if self.cancel_event.is_set():
            self.queue_handler.reset()
        self.calculate_hashes.reset_counters()

        self.button_cancel.set_visible(False)
        self.hide_progress()

        GLib.timeout_add(500, self.has_results, priority=GLib.PRIORITY_DEFAULT)

    def hide_progress(self):
        self.animate_opacity(self.progress_bar, 1, 0, 500)
        GLib.timeout_add(500, self.progress_bar.set_fraction, 0.0, priority=GLib.PRIORITY_DEFAULT)
        GLib.timeout_add(1000, self.scroll_to_bottom, priority=GLib.PRIORITY_DEFAULT)

    def notify_limit_breach(self):
        hash_result_row_count = HashResultRow.get_counter()
        max_rows = self.pref.max_rows()
        notified = self.pref.notified_of_limit_breach()

        if hash_result_row_count > max_rows and notified is False:
            self.add_toast(
                "<big>⚠️ Too many results! New results are now hidden from display for performance reasons.</big>",
                timeout=5,
                priority=Adw.ToastPriority.HIGH,
            )

            self.pref.set_notified_of_limit_breach(True)
            self.logger.debug(f"{hash_result_row_count} > {max_rows}, hiding new results")

        elif hash_result_row_count <= max_rows and notified:
            self.add_toast(
                "<big>✅ Results are now visible again. Displaying all results.</big>",
                timeout=3,
                priority=Adw.ToastPriority.NORMAL,
            )

            self.pref.set_notified_of_limit_breach(False)
            self.logger.debug(f"{hash_result_row_count} <= {max_rows}, showing new results.")

        return hash_result_row_count > max_rows

    def update_badge_numbers(self):
        self.results_stack_page.set_badge_number(HashResultRow.get_counter() - HashResultRow.get_counter_hidden())
        self.errors_stack_page.set_badge_number(HashErrorRow.get_counter())
        self.update_hidden_row_counter()

    def update_hidden_row_counter(self):
        hidden_count = HashResultRow.get_counter_hidden()
        self.hidden_row_counter.get_child().set_label(label=f"Hidden: {hidden_count}")
        self.hidden_row_counter.set_visible(hidden_count > 0)

    def scroll_to_bottom(self):
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

    def animate_opacity(self, widget: Gtk.Widget, from_value: float, to_value: float, duration: int):
        animation = Adw.TimedAnimation.new(
            widget.get_parent(),
            from_value,
            to_value,
            duration,
            Adw.CallbackAnimationTarget.new(lambda opacity: widget.set_opacity(opacity)),
        )
        animation.play()

    def has_results(self, *signal_from_view_stack):
        has_results = HashResultRow.get_counter() > 0
        has_errors = HashErrorRow.get_counter() > 0
        save_errors = self.pref.save_errors()
        current_page_name = self.view_stack.get_visible_child_name()

        self.button_save.set_sensitive(has_results or (has_errors and save_errors))
        self.button_copy_all.set_sensitive(has_results or (has_errors and save_errors))
        self.button_sort.set_sensitive(has_results)
        self.button_clear.set_sensitive(has_results or has_errors)
        self.button_show_searchbar.set_sensitive(has_results or has_errors)
        self.update_badge_numbers()
        self.notify_limit_breach()

        show_empty = (current_page_name == "results" and not has_results) or (current_page_name == "errors" and not has_errors)
        relevant_placeholder = self.empty_placeholder if current_page_name == "results" else self.empty_error_placeholder
        target = relevant_placeholder if show_empty else self.main_content_overlay
        if self.toolbar_view.get_content() is target and not signal_from_view_stack:
            return
        self.toolbar_view.set_content(target)
        Adw.TimedAnimation(
            widget=self,
            value_from=0.3,
            value_to=1.0,
            duration=500,
            target=Adw.CallbackAnimationTarget.new(lambda opacity: target.set_opacity(opacity)),
        ).play()

    def results_to_txt(self):
        parts = []
        total_results = HashResultRow.get_counter()
        total_errors = HashErrorRow.get_counter()

        if total_results > 0:
            results_text = "\n".join(str(r) for r in self.ui_results if self.filter_func(r))
            parts.append(f"Results ({total_results}):\n\n{results_text}")

        if self.pref.save_errors() and total_errors > 0:
            errors_text = "\n".join(str(r) for r in self.ui_errors if self.filter_func_err(r))
            parts.append(f"Errors ({total_errors}):\n\n{errors_text}")

        if self.pref.include_time() and parts:
            now = datetime.now().astimezone().strftime("%B %d, %Y at %H:%M:%S %Z")
            parts.append(f"Generated on {now}")

        if parts:
            output = "\n\n".join(parts)
        else:
            output = ""

        return output

    def on_click_show_searchbar(self, *_):
        if self.button_show_searchbar.is_sensitive():
            self.search_entry.set_visible(True)
            self.search_entry.grab_focus()
        else:
            self.add_toast("<big>🔍 No Results. Search is unavailable.</big>")

    def on_hide_searchbar(self):
        self.search_entry.set_text("")
        self.search_entry.set_visible(False)

    def on_select_files_clicked(self, _):
        file_dialog = Gtk.FileDialog(title="Select Files")

        def on_files_dialog_dismissed(file_dialog: Gtk.FileDialog, gio_task: Gio.Task):
            if not gio_task.had_error():
                files = file_dialog.open_multiple_finish(gio_task)
                self.start_job(files, self.pref.get_algorithm(), self.pref.get_working_config())

        file_dialog.open_multiple(parent=self, callback=on_files_dialog_dismissed)

    def on_select_folders_clicked(self, _):
        file_dialog = Gtk.FileDialog(title="Select Folders")

        def on_files_dialog_dismissed(file_dialog: Gtk.FileDialog, gio_task: Gio.Task):
            if not gio_task.had_error():
                files = file_dialog.select_multiple_folders_finish(gio_task)
                self.start_job(files, self.pref.get_algorithm(), self.pref.get_working_config())

        file_dialog.select_multiple_folders(parent=self, callback=on_files_dialog_dismissed)

    def on_copy_all_clicked(self, button: Gtk.Button):
        if HashResultRow.get_counter() > self.pref.max_rows():
            self.add_toast("<big>❌ Too many results to copy. Please use the Save button instead.</big>")

        elif self.button_copy_all.is_sensitive():
            output = self.results_to_txt()
            clipboard = self.get_clipboard()
            clipboard.set(output)
            self.add_toast("<big>✅ Results copied to clipboard</big>")

    def on_save_clicked(self, _):
        if not self.button_save.is_sensitive():
            return
        file_dialog = Gtk.FileDialog(title="Save", initial_name="results.txt")

        def on_file_dialog_dismissed(file_dialog: Gtk.FileDialog, gio_task: Gio.Task):
            if not gio_task.had_error():
                try:
                    local_file = file_dialog.save_finish(gio_task)
                    path: str = local_file.get_path()

                    with open(path, "w", encoding="utf-8") as f:
                        f.write(self.results_to_txt())

                    self.add_toast(f"<big>✅ Saved to <b>{path}</b></big>")

                except Exception as e:
                    self.logger.error(f"Unexcepted error occured for {path}: {e}")
                    self.add_toast(f"<big>❌ Failed to save: {e}</big>")

        file_dialog.save(parent=self, callback=on_file_dialog_dismissed)

    def on_search_changed(self, entry: Gtk.SearchEntry, ui_list: Gtk.ListBox):
        self.search_query = entry.get_text().lower()
        ui_list.invalidate_filter()

    def on_sort_clicked(self, _):
        if self.button_sort.is_sensitive():
            self.ui_results.set_sort_func(self.sort_by_hierarchy)
            self.ui_results.set_sort_func(None)
            self.add_toast("<big>✅ Results sorted by file path</big>")

    def on_clear_clicked(self, _):
        if self.button_clear.is_sensitive():
            HashResultRow.reset_counter()
            HashErrorRow.reset_counter()
            self.ui_results.remove_all()
            self.ui_errors.remove_all()
            self.pref.set_notified_of_limit_breach(False)
            self.has_results()
            self.view_stack.set_visible_child_name("results")
            self.add_toast("<big>✅ Results cleared</big>")

    def filter_func(self, row: HashResultRow):
        if not self.search_query:
            row.set_visible(not row.is_hidden_result())
            return True

        terms = self.search_query.split()
        fields = (row.path.as_posix().lower(), row.hash_value, row.algo)
        has_term = all(any(term in field for field in fields) for term in terms)

        if has_term:
            if not row.get_visible():
                row.set_visible(True)
            return True

        if row.is_hidden_result() and row.get_visible() and not has_term:
            row.set_visible(False)
        return False

    def filter_func_err(self, row: HashErrorRow):
        if not self.search_query:
            return True

        terms = self.search_query.split()
        fields = (row.path.as_posix().lower(), row.error_message)

        return all(any(term in field for field in fields) for term in terms)

    def add_toast(self, toast_label: str, timeout: int = 2, priority=Adw.ToastPriority.NORMAL):
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

    def create_win_action(self, name, callback):
        action = Gio.SimpleAction.new(name=name, parameter_type=None)
        action.connect("activate", callback)
        self.add_action(action=action)


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE | Gio.ApplicationFlags.HANDLES_OPEN)
        self.logger = get_logger(self.__class__.__name__)
        self.pref = Preferences()
        self.create_actions()
        self.create_options()

    def do_startup(self):
        Adw.Application.do_startup(self)

    def do_shutdown(self):
        self.logger.debug("Application shutdown")
        if hasattr(self, "main_window"):
            self.main_window.cancel_event.set()
        Adw.Application.do_shutdown(self)

    def do_handle_local_options(self, options):
        self.logger.debug("Application handle local options")
        if options.contains("list-choices"):
            for i, algo in enumerate(AVAILABLE_ALGORITHMS):
                if i % 4 == 0 and i > 0:
                    print()
                print(f"{algo:<15}", end="")
            print()
            return 0
        return -1  # Continue

    def do_command_line(self, command_line):
        cli_options: dict = command_line.get_options_dict().end().unpack()
        self.logger.debug(f"Initial CLI options: {cli_options}")

        from_cli = "DESKTOP" not in cli_options
        cli_options.pop("DESKTOP", None)
        _config_ = None

        if from_cli:
            _config_ = self.pref.persisted_config
            algo = cli_options.get("algo", _config_.get("algo"))
            max_workers = cli_options.get("max-workers", _config_.get("max-workers"))

            if algo and algo not in AVAILABLE_ALGORITHMS:
                print(f"Unexpected hash algorithm: {algo}")
                return 1

            cli_options.update({"algo": algo, "max-workers": max_workers})

        if paths := command_line.get_arguments()[1:]:
            _config_ = cli_options or self.pref.get_working_config()
            os.chdir(command_line.get_cwd())
            paths = [Path(path).absolute() for path in paths]
            self.do_open(paths, len(paths), "", _config_.get("algo"), _config_)

        else:
            if from_cli:
                _config_ = cli_options
                self.pref.apply_options_ui(_config_)
            self.do_activate()

        self.logger.debug(f"Effective CLI options out: {_config_}")
        return 0

    def do_activate(self):
        self.logger.debug(f"App {self.get_application_id()} activated")
        self.main_window: MainWindow = self.get_active_window()
        if not self.main_window:
            self.main_window: MainWindow = MainWindow(self)
        self.main_window.present()

    def do_open(self, files, n_files, hint, hash_algorithm=None, options={}):
        self.logger.debug(f"App {self.get_application_id()} opened with files ({n_files})")
        self.main_window: MainWindow = self.get_active_window()
        if not self.main_window:
            self.main_window: MainWindow = MainWindow(self)
        self.main_window.present()
        self.main_window.start_job(files, hash_algorithm, options)

    def create_action(self, name, callback, parameter_type=None, shortcuts=None):
        action = Gio.SimpleAction.new(name=name, parameter_type=parameter_type)
        action.connect("activate", callback)
        self.add_action(action=action)
        if shortcuts:
            self.set_accels_for_action(
                detailed_action_name=f"app.{name}",
                accels=shortcuts,
            )

    def create_actions(self):
        self.create_action("show-searchbar", lambda *_: self.main_window.on_click_show_searchbar(), shortcuts=["<Ctrl>F"])
        self.create_action("hide-searchbar", lambda *_: self.main_window.on_hide_searchbar(), shortcuts=["Escape"])

        self.create_action("results-copy", lambda *_: self.main_window.on_copy_all_clicked(_), shortcuts=["<Ctrl>C"])
        self.create_action("results-save", lambda *_: self.main_window.on_save_clicked(_), shortcuts=["<Ctrl>S"])
        self.create_action("results-sort", lambda *_: self.main_window.on_sort_clicked(_), shortcuts=["<Ctrl>R"])
        self.create_action("results-clear", lambda *_: self.main_window.on_clear_clicked(_), shortcuts=["<Ctrl>L"])

        self.create_action("open-files", lambda *_: self.main_window.on_select_files_clicked(_), shortcuts=["<Ctrl>O"])
        self.create_action("preferences", lambda *_: self.pref.present(), shortcuts=["<Ctrl>comma"])
        self.create_action("shortcuts", lambda *_: self.main_window.shortcuts_window.present(), shortcuts=["<Ctrl>question"])
        self.create_action("about", lambda *_: self.main_window.about_window.present())

        self.create_action("set-recursive-mode", lambda *_: self.pref.set_recursive_mode(*_), GLib.VariantType.new("s"))
        self.create_action("quit", lambda *_: self.quit(), shortcuts=["<Ctrl>Q"])

    def create_options(self):
        self.set_option_context_summary("Quick File Hasher - Modern Nautilus Extension and GTK4 App")
        self.set_option_context_parameter_string("[FILE|FOLDER...] [--recursive] [--gitignore] [--max-workers 4] [--algo sha256]")
        self.add_main_option("algo", ord("a"), GLib.OptionFlags.NONE, GLib.OptionArg.STRING, "Default hashing algorithm", "ALGORITHM")
        self.add_main_option("recursive", ord("r"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE, "Process files within subdirectories", None)
        self.add_main_option("gitignore", ord("g"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE, "Skip files/folders listed in .gitignore", None)
        self.add_main_option("max-workers", ord("w"), GLib.OptionFlags.NONE, GLib.OptionArg.INT, "Maximum number of parallel hashing operations", "N")
        self.add_main_option("list-choices", ord("l"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE, "List available hash algorithms", None)
        self.add_main_option("DESKTOP", 0, GLib.OptionFlags.HIDDEN, GLib.OptionArg.NONE, "Invoked from the Desktop Environment", None)


if __name__ == "__main__":
    app = Application()
    app.run(sys.argv)
