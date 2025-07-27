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
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import lru_cache
from itertools import repeat
from pathlib import Path
from queue import Empty, Queue
from typing import Callable, Literal

import gi  # type: ignore

gi.require_version(namespace="Gtk", version="4.0")
gi.require_version(namespace="Adw", version="1")
gi.require_version(namespace="Nautilus", version="4.0")

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Nautilus, Pango  # type: ignore

Adw.init()

APP_ID = "com.github.dd-se.quick-file-hasher"
APP_VERSION = "0.9.70"

DEFAULTS = {
    "default_hash_algorithm": "sha256",
    "max_visible_results": 100,
    "max_workers": 4,
    "recursive_mode": False,
    "respect_gitignore": False,
    "save_errors": False,
}
CONFIG_DIR = Path.home() / ".config" / APP_ID
CONFIG_FILE = CONFIG_DIR / "config.json"

VIEW_SWITCHER_CSS = b"""
.view-switcher button {
    background-color: #404040;
    color: white;
    transition: background-color 0.5s ease;
    }
.view-switcher button:nth-child(1):hover {
    background-color: #2b66b8;
}
.view-switcher button:nth-child(1):active {
    background-color: #1c457e;
}
.view-switcher button:nth-child(1):checked {
    background-color: #2b66b8;
}
.view-switcher button:nth-child(2):hover {
    background-color: #c7162b;
}
.view-switcher button:nth-child(2):active {
    background-color: #951323;
}
.view-switcher button:nth-child(2):checked {
    background-color: #c7162b;
}
"""

css_provider = Gtk.CssProvider()
css_provider.load_from_data(VIEW_SWITCHER_CSS)
Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def get_logger(name: str) -> logging.Logger:
    loglevel_str = os.getenv("LOGLEVEL", "INFO").upper()
    loglevel = getattr(logging, loglevel_str, logging.INFO)
    logger = logging.getLogger(name)
    logger.setLevel(loglevel)
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] %(levelname)-6s | %(name)-15s | %(funcName)-21s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


class AdwNautilusExtension(GObject.GObject, Nautilus.MenuProvider):
    def __init__(self):
        self.logger = get_logger(self.__class__.__name__)

    def nautilus_launch_app(self, menu_item: Nautilus.MenuItem, files: list[Nautilus.FileInfo], recursive_mode: bool = False):
        self.logger.info(f"App {APP_ID} launched by file manager")
        file_paths = [f.get_location().get_path() for f in files if f.get_location()]
        cmd = ["python3", __file__] + file_paths
        env = None
        if recursive_mode:
            env = os.environ.copy()
            env["CH_RECURSIVE_MODE"] = "yes"
            os.system(f"gapplication action {APP_ID} set-recursive-mode \"'yes'\"")

        else:
            os.system(f"gapplication action {APP_ID} set-recursive-mode \"'no'\"")

        subprocess.Popen(cmd, env=env)

    def create_menu(self, files, caller):
        if any(f.is_directory() for f in files):
            menu = Nautilus.MenuItem(
                name=f"AdwNautilusExtension::OpenInAppMenu_{caller}",
                label="Calculate Hashes Menu",
            )
            submenu = Nautilus.Menu()
            menu.set_submenu(submenu)

            item_normal = Nautilus.MenuItem(
                name=f"AdwNautilusExtension::OpenInAppNormal_{caller}",
                label="Calculate Hashes",
            )
            item_normal.connect("activate", self.nautilus_launch_app, files)
            submenu.append_item(item_normal)

            item_recursive = Nautilus.MenuItem(
                name=f"AdwNautilusExtension::OpenInAppRecursive_{caller}",
                label="Calculate Hashes (Recursive)",
            )
            item_recursive.connect("activate", self.nautilus_launch_app, files, True)
            submenu.append_item(item_recursive)
            return [menu]
        else:
            item = Nautilus.MenuItem(
                name=f"AdwNautilusExtension::OpenInAppNormal_{caller}",
                label="Calculate Hashes",
            )
            item.connect("activate", self.nautilus_launch_app, files)
            return [item]

    def get_background_items(self, current_folder: Nautilus.FileInfo) -> list[Nautilus.MenuItem]:
        if not current_folder.is_directory():
            return []
        return self.create_menu([current_folder], 1)

    def get_file_items(self, files: list[Nautilus.FileInfo]) -> list[Nautilus.MenuItem]:
        if not files:
            return []
        return self.create_menu(files, 2)


class Preferences(Adw.PreferencesDialog):
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
        self.logger = get_logger(self.__class__.__name__)
        self.set_title("Preferences")
        self.set_size_request(0, MainWindow.DEFAULT_HEIGHT - 100)
        self.set_search_enabled(True)

        self.load_config_file()
        self.setup_processing_page()
        self.setup_saving_page()
        self.setup_hashing_page()

        self.process_env_variables()
        self.connect("closed", self.on_close)
        self._initialized = True

    def setup_processing_page(self):
        processing_page = Adw.PreferencesPage()
        processing_page.set_title("Processing")
        processing_page.set_icon_name("edit-find-symbolic")
        self.add(processing_page)

        processing_group = Adw.PreferencesGroup()
        processing_group.set_description(description="Configure how files and folders are processed")
        processing_page.add(group=processing_group)

        self.setting_recursive = Adw.SwitchRow()
        self.setting_recursive.add_prefix(widget=Gtk.Image.new_from_icon_name(icon_name="edit-find-symbolic"))
        self.setting_recursive.set_title(title="Recursive Traversal")
        self.setting_recursive.set_subtitle(subtitle="Enable to process all files in subdirectories")
        self.setting_recursive.set_active(self.config["recursive_mode"])
        self.setting_recursive.connect("notify::active", self.on_switch_row_changed, "recursive_mode")
        processing_group.add(child=self.setting_recursive)

        self.setting_gitignore = Adw.SwitchRow()
        self.setting_gitignore.add_prefix(widget=Gtk.Image.new_from_icon_name(icon_name="action-unavailable-symbolic"))
        self.setting_gitignore.set_title(title="Respect .gitignore")
        self.setting_gitignore.set_subtitle(subtitle="Skip files and folders listed in .gitignore file")
        self.setting_gitignore.set_active(self.config["respect_gitignore"])
        self.setting_gitignore.connect("notify::active", self.on_switch_row_changed, "respect_gitignore")
        processing_group.add(child=self.setting_gitignore)
        processing_group.add(self.create_buttons())

    def setup_saving_page(self):
        saving_page = Adw.PreferencesPage()
        saving_page.set_title("Saving")
        saving_page.set_icon_name("document-save-symbolic")
        self.add(saving_page)

        saving_group = Adw.PreferencesGroup()
        saving_group.set_description(description="Configure how results are saved")
        saving_page.add(group=saving_group)

        self.setting_save_errors = Adw.SwitchRow()
        self.setting_save_errors.add_prefix(widget=Gtk.Image.new_from_icon_name(icon_name="dialog-error-symbolic"))
        self.setting_save_errors.set_title(title="Save errors")
        self.setting_save_errors.set_subtitle(subtitle="Save errors to results file or clipboard")
        self.setting_save_errors.set_active(self.config["save_errors"])
        self.setting_save_errors.connect("notify::active", lambda *_: MainWindow().has_results())
        self.setting_save_errors.connect("notify::active", self.on_switch_row_changed, "save_errors")

        saving_group.add(child=self.setting_save_errors)
        saving_group.add(child=self.create_buttons())

    def setup_hashing_page(self):
        hashing_page = Adw.PreferencesPage()
        hashing_page.set_title("Hashing")
        hashing_page.set_icon_name("dialog-password-symbolic")
        self.add(hashing_page)

        hashing_group = Adw.PreferencesGroup()
        hashing_group.set_description(description="Configure hashing behavior")
        hashing_page.add(group=hashing_group)

        self.setting_max_workers = Adw.SpinRow.new(Gtk.Adjustment.new(4, 1, 16, 1, 5, 0), 1, 0)
        self.setting_max_workers.set_editable(True)
        self.setting_max_workers.set_numeric(True)
        self.setting_max_workers.add_prefix(widget=Gtk.Image.new_from_icon_name(icon_name="process-working-symbolic"))
        self.setting_max_workers.set_title(title="Max Workers")
        self.setting_max_workers.set_subtitle(subtitle="Set how many files are hashed in parallel")
        self.setting_max_workers.set_value(self.config["max_workers"])
        self.setting_max_workers.connect("notify::value", self.on_spin_row_changed, "max_workers")
        hashing_group.add(child=self.setting_max_workers)

        self.drop_down_algo_button = Adw.ComboRow()
        self.drop_down_algo_button.add_prefix(Gtk.Image.new_from_icon_name("dialog-password-symbolic"))
        self.available_algorithms = sorted(hashlib.algorithms_guaranteed)
        self.max_width_label = max(len(algo) for algo in self.available_algorithms)
        self.drop_down_algo_button.set_model(Gtk.StringList.new(self.available_algorithms))
        self.drop_down_algo_button.set_title("Hashing Algorithm")
        self.drop_down_algo_button.set_subtitle("Select the default hashing algorithm for new jobs")
        self.drop_down_algo_button.set_selected(self.available_algorithms.index(self.config["default_hash_algorithm"]))
        self.drop_down_algo_button.set_valign(Gtk.Align.CENTER)
        self.drop_down_algo_button.connect("notify::selected", self.on_algo_selected)

        hashing_group.add(child=self.drop_down_algo_button)
        hashing_group.add(child=self.create_buttons())

    def create_buttons(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        main_box.append(spacer)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        button_box.set_margin_top(20)
        main_box.append(button_box)

        button_save_preferences = Gtk.Button(label="Persist")
        button_save_preferences.set_tooltip_text("Persist current preferences to config file")
        button_save_preferences.connect("clicked", lambda _: self.save_preferences_to_config_file())
        button_save_preferences.set_hexpand(True)
        button_box.append(button_save_preferences)

        button_reset_preferences = Gtk.Button(label="Reset")
        button_reset_preferences.add_css_class("destructive-action")
        button_reset_preferences.set_tooltip_text("Reset all preferences to default values")
        button_reset_preferences.connect("clicked", lambda _: self.reset_preferences())
        button_reset_preferences.set_hexpand(True)
        button_box.append(button_reset_preferences)
        return main_box

    def load_config_file(self):
        self.config = DEFAULTS.copy()
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)

                self.config.update(config)
                self.logger.debug(f"Loaded preferences from {CONFIG_FILE}")

        except json.JSONDecodeError as e:
            self.logger.error(f"{CONFIG_FILE}: {e}. Using defaults.")
            MainWindow().add_toast(f"Error decoding JSON from {CONFIG_FILE}. Using defaults.", priority=Adw.ToastPriority.HIGH)

        except Exception as e:
            self.logger.error(f"{CONFIG_FILE}: {e}. Using defaults.")
            MainWindow().add_toast(f"Unexpected error loading config from {CONFIG_FILE}. Using defaults.", priority=Adw.ToastPriority.HIGH)

    def save_preferences_to_config_file(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)

            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, sort_keys=True)

            self.add_toast(Adw.Toast(title="<big>Success!</big>", use_markup=True, timeout=1))
            self.logger.info(f"Preferences saved to file: {CONFIG_FILE}")

        except Exception as e:
            self.add_toast(Adw.Toast(title=str(e)))
            self.logger.error(f"Error saving preferences to {CONFIG_FILE}: {e}")

    def reset_preferences(self):
        self.setting_recursive.set_active(DEFAULTS["recursive_mode"])
        self.setting_gitignore.set_active(DEFAULTS["respect_gitignore"])
        self.setting_save_errors.set_active(DEFAULTS["save_errors"])
        self.setting_max_workers.set_value(DEFAULTS["max_workers"])
        self.drop_down_algo_button.set_selected(self.available_algorithms.index(DEFAULTS["default_hash_algorithm"]))
        self.add_toast(Adw.Toast(title="<big>Success!</big>", use_markup=True, timeout=1))

    def process_env_variables(self):
        recursive_mode = os.getenv("CH_RECURSIVE_MODE")
        if recursive_mode:
            state = recursive_mode.lower() == "yes"
            self.setting_recursive.set_active(state)
            self.setting_gitignore.set_active(state)
            self.logger.info(f"Recursive mode set to {state} via env variable")

    def recursive_mode(self):
        return self.setting_recursive.get_active()

    def respect_gitignore(self):
        return self.setting_gitignore.get_active()

    def save_errors(self):
        return self.setting_save_errors.get_active()

    def max_workers(self):
        return self.setting_max_workers.get_value()

    def max_rows(self) -> int:
        return self.config["max_visible_results"]

    def notified_of_limit_breach(self) -> bool:
        return self._notified_of_limit_breach

    def hashing_algorithm(self) -> str:
        return self.drop_down_algo_button.get_selected_item().get_string()

    def set_notified_of_limit_breach(self, state: bool):
        self._notified_of_limit_breach = state

    def on_switch_row_changed(self, switch_row: Adw.SwitchRow, param: GObject.ParamSpec, config_key: str):
        new_value = switch_row.get_active()
        if self.config.get(config_key) != new_value:
            self.config[config_key] = new_value
            self.logger.info(f"Switch Preference '{config_key}' changed to '{new_value}'")

    def on_spin_row_changed(self, spin_row: Adw.SpinRow, param: GObject.ParamSpec, config_key: str):
        new_value = int(spin_row.get_value())
        if self.config.get(config_key) != new_value:
            self.config[config_key] = new_value
            self.logger.info(f"Spin Preference '{config_key}' changed to {new_value}")

    def on_algo_selected(self, drop_down: Gtk.DropDown, g_param_object):
        selected_hashing_algorithm = self.hashing_algorithm()
        if self.config.get("default_hash_algorithm") != selected_hashing_algorithm:
            self.config["default_hash_algorithm"] = selected_hashing_algorithm
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
    def __init__(
        self,
        queue: QueueUpdateHandler,
        event: threading.Event,
    ):
        self.logger = get_logger(self.__class__.__name__)
        self.pref: Preferences = Preferences()
        self.queue_handler = queue
        self.cancel_event = event
        self.total_bytes = 0
        self.bytes_read = 0

    def execute_jobs(self, jobs: dict[str, list], hash_algorithms: str | list):
        hash_algorithms = repeat(hash_algorithms) if isinstance(hash_algorithms, str) else hash_algorithms
        with ThreadPoolExecutor(max_workers=self.pref.max_workers()) as executor:
            self.logger.debug(f"Starting hashing with {self.pref.max_workers()} workers")
            list(executor.map(self.hash_task, jobs["paths"], hash_algorithms, jobs["sizes"]))

    def __call__(self, paths: list[Path] | list[Gio.File], hash_algorithm: list | str):
        jobs = self.create_jobs(paths)
        self.execute_jobs(jobs, hash_algorithm)

    def create_jobs(self, paths: list[Path] | list[Gio.File]):
        jobs = {"paths": [], "sizes": []}

        for root_path in paths:
            try:
                if issubclass(type(root_path), Gio.File):
                    root_path = Path(root_path.get_path())

                ignore_rules = []

                if root_path.is_dir():
                    if self.pref.respect_gitignore():
                        gitignore_file = root_path / ".gitignore"

                        if gitignore_file.exists():
                            ignore_rules = IgnoreRule.parse_gitignore(gitignore_file)
                            self.logger.debug(f"Added rule early: {gitignore_file} ({len(ignore_rules)})")

                    for sub_path in root_path.iterdir():
                        if IgnoreRule.is_ignored(sub_path, ignore_rules):
                            self.logger.debug(f"Skipped early: {sub_path}")
                            continue
                        self.process_path_n_rules(sub_path, ignore_rules, jobs)
                else:
                    self.process_path_n_rules(root_path, ignore_rules, jobs)

            except Exception as e:
                self.logger.debug(f"Error processing {root_path.name}: {e}")
                self.queue_handler.update_error(root_path, str(e))

        if self.total_bytes == 0:
            self.queue_handler.update_progress(1, 1)

        return jobs

    def process_path_n_rules(self, current_path: Path, current_rules: list[IgnoreRule], jobs: dict[str, list]):
        # self.logger.debug(f"Job started for: {hash_algorithm}:{current_path.name} with rules: {len(current_rules)}")
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
                    self.queue_handler.update_error(current_path, "File is empty")

                else:
                    self.add_bytes(file_size)
                    jobs["paths"].append(current_path)
                    jobs["sizes"].append(file_size)

            elif current_path.is_dir() and self.pref.recursive_mode():
                local_rules = []

                if self.pref.respect_gitignore():
                    local_rules = current_rules.copy()
                    gitignore_file = current_path / ".gitignore"

                    if gitignore_file.exists():
                        IgnoreRule.parse_gitignore(gitignore_file, extend=local_rules)
                        self.logger.debug(f"Added rule late: {gitignore_file} ({len(local_rules)})")

                for sub_path in current_path.iterdir():
                    self.process_path_n_rules(sub_path, local_rules, jobs)

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

    def add_bytes(self, bytes_: int):
        self.total_bytes += bytes_

    def reset_counters(self):
        self.bytes_read = 0
        self.total_bytes = 0


class HashRow(Adw.ActionRow):
    _counter = 0
    _counter_hidden = 0

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
    def reset_counter(cls):
        cls._counter = 0
        cls._counter_hidden = 0

    @classmethod
    def increment_counter_hidden(cls):
        cls._counter_hidden += 1
        return cls._counter_hidden

    @classmethod
    def decrement_counter_hidden(cls):
        if cls._counter_hidden > 0:
            cls._counter_hidden -= 1
        return cls._counter_hidden

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

    def on_delete_clicked(self, button: Gtk.Button):
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

        self.hash_icon = Gtk.Image.new_from_icon_name("text-x-generic-symbolic")
        self.hash_icon_name = self.hash_icon.get_icon_name()
        self.prefix_hash_box.append(self.hash_icon)

        self.hash_name = Gtk.Label(label=self.algo.upper())
        self.hash_name.set_width_chars(Preferences().max_width_label)
        self.prefix_hash_box.append(self.hash_name)

        self.add_prefix(self.prefix_hash_box)

        self.button_make_hashes = Gtk.Button()
        self.button_make_hashes.set_child(Gtk.Label(label="Multi-Hash"))
        self.button_make_hashes.set_valign(Gtk.Align.CENTER)
        self.button_make_hashes.set_tooltip_text("Select and compute multiple hash algorithms for this file")
        self.button_make_hashes.connect("clicked", self.on_click_make_hashes)

        self.button_copy_hash = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
        self.button_copy_hash.set_valign(Gtk.Align.CENTER)
        self.button_copy_hash.set_tooltip_text("Copy hash")
        self.button_copy_hash.connect("clicked", self.on_copy_clicked)

        self.button_compare = Gtk.Button.new_from_icon_name("edit-paste-symbolic")
        self.button_compare.set_valign(Gtk.Align.CENTER)
        self.button_compare.set_tooltip_text("Compare with clipboard")
        self.button_compare.connect("clicked", self.on_compare_clicked)

        self.button_delete = Gtk.Button.new_from_icon_name("user-trash-symbolic")
        self.button_delete.set_valign(Gtk.Align.CENTER)
        self.button_delete.set_tooltip_text("Remove this result")
        self.button_delete.connect("clicked", self.on_delete_clicked)

        self.add_suffix(self.button_make_hashes)
        self.add_suffix(self.button_copy_hash)
        self.add_suffix(self.button_compare)
        self.add_suffix(self.button_delete)

        self.set_hidden_result(self.get_counter() > Preferences().max_rows())

    def __str__(self):
        return f"{self.path}:{self.hash_value}:{self.algo}"

    def on_click_make_hashes(self, button: Gtk.Button):
        dialog = Adw.AlertDialog(body="<big><b>Select Hashing Algorithms</b></big>", body_use_markup=True)
        dialog.set_presentation_mode(Adw.DialogPresentationMode.BOTTOM_SHEET)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("compute", "Compute")
        dialog.set_response_appearance("compute", Adw.ResponseAppearance.SUGGESTED)
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
        count = 0
        for algo in Preferences().available_algorithms:
            if algo != self.algo:
                if count % 5 == 0:
                    current_list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
                    current_list_box.add_css_class("boxed-list")
                    horizontal_container.append(current_list_box)

                switch = Adw.SwitchRow()
                switch.add_prefix(Gtk.Label(label=algo.upper()))
                switch.add_prefix(Gtk.Image.new_from_icon_name("dialog-password-symbolic"))

                switches.append((switch, algo))
                current_list_box.append(switch)
                count += 1

        def on_button_click(_, state: bool):
            for switch, _ in switches:
                switch.set_active(state)

        select_all_button.connect("clicked", on_button_click, True)
        deselect_all_button.connect("clicked", on_button_click, False)

        def on_response(_, response_id):
            if response_id == "compute":
                selected_algos = [algo for (check, algo) in switches if check.get_active()]
                if selected_algos:
                    paths = [self.path] * len(selected_algos)
                    MainWindow().start_job(paths, selected_algos)

        dialog.connect("response", on_response)
        dialog.present(MainWindow())

    def on_copy_clicked(self, button: Gtk.Button):
        button.set_sensitive(False)
        button.get_clipboard().set(self.hash_value)
        original_child = button.get_child()
        button.set_child(Gtk.Label(label="Copied!"))
        GLib.timeout_add(1500, lambda: (button.set_child(original_child), button.set_sensitive(True)))

    def on_compare_clicked(self, button: Gtk.Button):
        def handle_clipboard_comparison(clipboard, result):
            try:
                self.button_compare.set_sensitive(False)
                clipboard_text: str = clipboard.read_text_finish(result).strip()
                if clipboard_text == self.hash_value:
                    self.set_icon_("object-select-symbolic")
                    self.set_css_("success")
                    MainWindow().add_toast(f"<big>✅ Clipboard hash matches <b>{self.get_title()}</b>!</big>")
                else:
                    self.set_icon_("dialog-error-symbolic")
                    self.set_css_("error")
                    MainWindow().add_toast(f"<big>❌ The clipboard hash does <b>not</b> match <b>{self.get_title()}</b>!</big>")

                GLib.timeout_add(
                    3000,
                    lambda: (
                        self.reset_css(),
                        self.reset_icon(),
                        self.button_compare.set_sensitive(True),
                    ),
                )
            except Exception as e:
                self.logger.exception(f"Error reading clipboard: {e}")
                MainWindow().add_toast(f"<big>❌ Clipboard read error: {e}</big>")

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

        self.button_copy_error = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
        self.button_copy_error.set_valign(Gtk.Align.CENTER)
        self.button_copy_error.set_tooltip_text("Copy error message")
        self.button_copy_error.connect("clicked", self.on_copy_error_clicked)
        self.add_suffix(self.button_copy_error)

        self.add_css_class("error")

    def __str__(self) -> str:
        return f"{self.path}:ERROR:{self.error_message}"

    def on_copy_error_clicked(self, button: Gtk.Button) -> None:
        button.set_sensitive(False)
        button.get_clipboard().set(self.error_message)
        original_child = button.get_child()
        button.set_child(Gtk.Label(label="Copied!"))
        GLib.timeout_add(1500, lambda: (button.set_child(original_child), button.set_sensitive(True)))


class MainWindow(Adw.ApplicationWindow):
    DEFAULT_WIDTH = 970
    DEFAULT_HEIGHT = 650
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, app=None, paths: list[Path] | list[Gio.File] | None = None):
        if hasattr(self, "_initialized"):
            return
        super().__init__(application=app)
        self.logger = get_logger(self.__class__.__name__)
        self.set_default_size(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        self.set_size_request(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        self.build_ui()
        self._initialized = True

        self.pref = Preferences()
        self.queue_handler = QueueUpdateHandler()
        self.cancel_event = threading.Event()
        self.calculate_hashes = CalculateHashes(self.queue_handler, self.cancel_event)

        if paths:
            self.start_job(paths)

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

        self.setup_about_dialog()

    def setup_toolbar_view(self):
        self.empty_placeholder = Adw.StatusPage(
            title="No Results",
            description="Select files or folders to calculate their hashes.",
            icon_name="text-x-generic-symbolic",
        )
        self.empty_error_placeholder = Adw.StatusPage(
            title="No Errors",
            description="   ",
            icon_name="object-select-symbolic",
        )
        self.toolbar_view = Adw.ToolbarView()
        self.toolbar_view.set_margin_top(6)
        self.toolbar_view.set_margin_bottom(6)
        self.toolbar_view.set_margin_start(12)
        self.toolbar_view.set_margin_end(12)

    def setup_first_top_bar(self):
        self.first_top_bar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, margin_bottom=10)

        self.button_select_files = Gtk.Button()
        self.button_select_files.add_css_class("suggested-action")
        self.button_select_files.set_valign(Gtk.Align.CENTER)
        self.button_select_files.set_tooltip_text("Select files to add")
        self.button_select_files.connect("clicked", self.on_select_files_clicked)
        self.button_select_files_content = Adw.ButtonContent.new()
        self.button_select_files_content.set_icon_name(icon_name="document-open-symbolic")
        self.button_select_files_content.set_label(label="Select Files")
        self.button_select_files.set_child(self.button_select_files_content)
        self.first_top_bar_box.append(self.button_select_files)

        self.button_select_folders = Gtk.Button()
        self.button_select_folders.add_css_class("suggested-action")
        self.button_select_folders.set_valign(Gtk.Align.CENTER)
        self.button_select_folders.set_tooltip_text("Select folders to add")
        self.button_select_folders.connect("clicked", self.on_select_folders_clicked)
        self.button_select_folders_content = Adw.ButtonContent.new()
        self.button_select_folders_content.set_icon_name(icon_name="folder-open-symbolic")
        self.button_select_folders_content.set_label(label="Select Folders")
        self.button_select_folders.set_child(self.button_select_folders_content)
        self.first_top_bar_box.append(self.button_select_folders)

        self.button_save = Gtk.Button()
        self.button_save.set_sensitive(False)
        self.button_save.add_css_class("suggested-action")
        self.button_save.set_valign(Gtk.Align.CENTER)
        self.button_save.set_tooltip_text("Save results to file")
        self.button_save.connect("clicked", self.on_save_clicked)
        self.button_save_content = Adw.ButtonContent.new()
        self.button_save_content.set_icon_name(icon_name="document-save-symbolic")
        self.button_save_content.set_label(label="Save")
        self.button_save.set_child(self.button_save_content)
        self.first_top_bar_box.append(self.button_save)

        self.button_cancel = Gtk.Button(label="Cancel Jobs")
        self.button_cancel.add_css_class("destructive-action")
        self.button_cancel.set_valign(Gtk.Align.CENTER)
        self.button_cancel.set_visible(False)
        self.button_cancel.connect(
            "clicked",
            lambda _: (
                self.cancel_event.set(),
                self.add_toast("<big>❌ Jobs Cancelled</big>"),
            ),
        )
        self.first_top_bar_box.append(self.button_cancel)

        spacer_0 = Gtk.Box()
        spacer_0.set_hexpand(True)
        self.first_top_bar_box.append(spacer_0)

        self.setup_header_bar()
        self.first_top_bar_box.append(self.header_bar)

    def setup_second_top_bar(self):
        self.second_top_bar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, margin_bottom=5)

        self.view_switcher = Adw.ViewSwitcher()
        self.view_switcher.set_hexpand(True)
        self.view_switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        self.second_top_bar_box.append(self.view_switcher)

        self.hidden_row_counter = Gtk.Button()
        self.hidden_row_counter.set_valign(Gtk.Align.CENTER)
        self.hidden_row_counter.set_sensitive(False)
        self.hidden_row_counter_content = Adw.ButtonContent.new()
        self.hidden_row_counter_content.set_tooltip_text("Number of hidden results. Use search to reveal them.")
        self.hidden_row_counter_content.set_icon_name(icon_name="help-about-symbolic")
        self.hidden_row_counter_content.set_label(label="Hidden: 0")

        self.hidden_row_counter_content.set_use_underline(use_underline=True)
        self.hidden_row_counter.set_child(self.hidden_row_counter_content)
        self.second_top_bar_box.append(self.hidden_row_counter)

        spacer_1 = Gtk.Box()
        spacer_1.set_hexpand(True)
        self.second_top_bar_box.append(spacer_1)

        self.button_copy_all = Gtk.Button(label="Copy")
        self.button_copy_all.set_sensitive(False)
        self.button_copy_all.add_css_class("suggested-action")
        self.button_copy_all.set_valign(Gtk.Align.CENTER)
        self.button_copy_all.set_tooltip_text("Copy results to clipboard")
        self.button_copy_all.connect("clicked", self.on_copy_all_clicked)
        self.second_top_bar_box.append(self.button_copy_all)

        self.button_sort = Gtk.Button(label="Sort")
        self.button_sort.set_sensitive(False)
        self.button_sort.set_valign(Gtk.Align.CENTER)
        self.button_sort.set_tooltip_text("Sort results by path")

        self.button_sort.connect(
            "clicked",
            lambda _: (
                self.ui_results.set_sort_func(self.sort_by_hierarchy),
                self.ui_results.set_sort_func(None),
                self.add_toast("<big>✅ Results sorted by file path</big>"),
            ),
        )
        self.second_top_bar_box.append(self.button_sort)

        self.button_clear = Gtk.Button(label="Clear")
        self.button_clear.set_sensitive(False)
        self.button_clear.add_css_class("destructive-action")
        self.button_clear.set_valign(Gtk.Align.CENTER)
        self.button_clear.set_tooltip_text("Clear all results")
        self.button_clear.connect(
            "clicked",
            lambda _: (
                HashResultRow.reset_counter(),
                HashErrorRow.reset_counter(),
                self.ui_results.remove_all(),
                self.ui_errors.remove_all(),
                self.pref.set_notified_of_limit_breach(False),
                self.has_results(),
                self.view_stack.set_visible_child_name("results"),
                self.add_toast("<big>✅ Results cleared</big>"),
            ),
        )
        self.second_top_bar_box.append(self.button_clear)

    def setup_header_bar(self):
        self.header_bar = Adw.HeaderBar()
        self.header_title_widget = Gtk.Label(label="<big><b>Quick File Hasher</b></big>", use_markup=True)
        self.header_bar.set_title_widget(self.header_title_widget)
        self.setup_menu()
        self.setup_search()

    def setup_main_content(self):
        self.main_content_overlay = Gtk.Overlay()

        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.main_content_overlay.add_overlay(self.main_box)

        self.view_stack = Adw.ViewStack()
        self.view_stack.set_vexpand(True)
        self.view_stack.set_hexpand(True)
        self.view_switcher.set_stack(self.view_stack)
        self.view_switcher.add_css_class("view-switcher")

        self.results_group = Adw.PreferencesGroup()
        self.results_group.set_hexpand(True)
        self.results_group.set_vexpand(True)

        self.ui_results = Gtk.ListBox()
        self.ui_results.set_selection_mode(Gtk.SelectionMode.NONE)
        self.ui_results.add_css_class("boxed-list")
        self.ui_results.set_filter_func(self.filter_func)
        self.results_group.add(self.ui_results)

        self.results_scrolled_window = Gtk.ScrolledWindow()
        self.results_scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.results_scrolled_window.set_child(self.results_group)

        self.results_stack_page = self.view_stack.add_titled_with_icon(self.results_scrolled_window, "results", "Results", "view-list-symbolic")

        self.errors_group = Adw.PreferencesGroup()
        self.errors_group.set_hexpand(True)
        self.errors_group.set_vexpand(True)

        self.ui_errors = Gtk.ListBox()
        self.ui_errors.set_selection_mode(Gtk.SelectionMode.NONE)
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

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Type to filter & ESC to clear")
        self.search_entry.set_margin_bottom(2)
        self.search_entry.set_visible(False)
        for ui_list in (self.ui_results, self.ui_errors):
            self.search_entry.connect("search-changed", self.on_search_changed, ui_list)

        def on_search_key_pressed(controller, keyval, keycode, state):
            if keyval == Gdk.KEY_Escape:
                self.search_entry.set_text("")
                self.search_entry.set_visible(False)
            return True

        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", on_search_key_pressed)
        self.search_entry.add_controller(key_controller)
        self.search_query = ""
        self.main_box.append(self.search_entry)

    def setup_menu(self):
        self.menu = Gio.Menu()
        self.menu.append("Preferences", "win.preferences")
        self.menu.append("About", "win.about")
        self.menu.append("Quit", "app.quit")
        self.create_win_action("about", lambda *_: self.about.present(self))
        self.create_win_action("preferences", lambda *_: self.pref.present(self))
        self.button_menu = Gtk.MenuButton()
        self.button_menu.set_icon_name("open-menu-symbolic")
        self.button_menu.set_menu_model(self.menu)
        self.header_bar.pack_end(self.button_menu)

    def setup_search(self):
        self.button_show_searchbar = Gtk.ToggleButton()
        self.button_show_searchbar.set_tooltip_text("Show search bar to filter results and errors")
        self.button_show_searchbar.set_sensitive(False)
        self.button_show_searchbar.set_icon_name(icon_name="system-search-symbolic")

        self.button_show_searchbar.connect("clicked", self.on_click_show_searchbar)
        self.header_bar.pack_end(self.button_show_searchbar)

    def setup_progress_bar(self):
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_opacity(0)

    def setup_drag_and_drop(self):
        self.dnd = Adw.StatusPage(
            title="Drop Files Here",
            icon_name="folder-open-symbolic",
        )
        self.drop = Gtk.DropTargetAsync.new(None, Gdk.DragAction.COPY)
        self.drop.connect(
            "drag-enter",
            lambda *_: (
                self.toolbar_view.set_content(self.dnd),
                Gdk.DragAction.COPY,
            )[1],
        )
        self.drop.connect(
            "drag-leave",
            lambda *_: (
                self.has_results(),
                Gdk.DragAction.COPY,
            )[1],
        )

        def on_read_value(drop: Gdk.Drop, result):
            try:
                files: Gdk.FileList = drop.read_value_finish(result)
                action = Gdk.DragAction.COPY
            except Exception as e:
                action = 0
                self.add_toast(f"Drag & Drop failed: {e}")
            else:
                self.start_job(files)
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

    def setup_about_dialog(self):
        self.about = Adw.AboutDialog()
        self.about.set_application_name("Quick File Hasher")
        self.about.set_application_icon("document-properties")
        self.about.set_version(APP_VERSION)
        self.about.set_developer_name("Doğukan Doğru (dd-se)")
        self.about.set_license_type(Gtk.License(Gtk.License.MIT_X11))
        self.about.set_comments("A modern Nautilus extension and standalone GTK4/libadwaita app to calculate hashes.")
        self.about.set_website("https://github.com/dd-se/nautilus-extension-quick-file-hasher")
        self.about.set_issue_url("https://github.com/dd-se/nautilus-extension-quick-file-hasher/issues")
        self.about.set_copyright("© 2025 Doğukan Doğru (dd-se)")
        self.about.set_developers(["dd-se https://github.com/dd-se"])
        self.about.connect("closed", lambda _: self.search_entry.grab_focus())

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

    def start_job(self, paths: list[Path] | list[Gio.File], hashing_algorithm: str | list | None = None):
        self.cancel_event.clear()
        self.button_cancel.set_visible(True)

        self.processing_thread = threading.Thread(
            target=self.calculate_hashes,
            args=(
                paths,
                hashing_algorithm or self.pref.hashing_algorithm(),
            ),
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
                GLib.timeout_add(500, self.ui_results.append, HashResultRow(*update[1:]))

            elif kind == "error":
                iterations += 1
                GLib.timeout_add(500, self.ui_errors.append, HashErrorRow(*update[1:]))

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
        self.hidden_row_counter_content.set_label(label=f"Hidden: {hidden_count}")
        self.hidden_row_counter.set_sensitive(hidden_count > 0)

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
        output = ""
        results_text = "\n".join(str(r) for r in self.ui_results if self.filter_func(r))
        now = datetime.now().astimezone().strftime("%B %d, %Y at %H:%M:%S %Z")

        if results_text:
            output = f"Results - Saved on {now}\n{'-' * 50}\n{results_text} {'\n\n' if self.pref.save_errors() else '\n'}"

        if self.pref.save_errors():
            errors_text = "\n".join(str(r) for r in self.ui_errors if self.filter_func_err(r))

            if errors_text:
                output = f"{output}Errors - Saved on {now}\n{'-' * 50}\n{errors_text}\n"

        return output

    def on_click_show_searchbar(self, *_):
        if self.button_show_searchbar.is_sensitive():
            self.search_entry.set_visible(True)
            self.search_entry.grab_focus()
        else:
            self.add_toast("<big>🔍 No Results. Search is unavailable.</big>")

    def on_select_files_clicked(self, _):
        file_dialog = Gtk.FileDialog()
        file_dialog.set_title(title="Select files")

        def on_files_dialog_dismissed(file_dialog: Gtk.FileDialog, gio_task: Gio.Task):
            if not gio_task.had_error():
                files = file_dialog.open_multiple_finish(gio_task)
                self.start_job(files)

        file_dialog.open_multiple(
            parent=self,
            callback=on_files_dialog_dismissed,
        )

    def on_select_folders_clicked(self, _):
        file_dialog = Gtk.FileDialog()
        file_dialog.set_title(title="Select Folders")

        def on_files_dialog_dismissed(file_dialog: Gtk.FileDialog, gio_task: Gio.Task):
            if not gio_task.had_error():
                files = file_dialog.select_multiple_folders_finish(gio_task)
                self.start_job(files)

        file_dialog.select_multiple_folders(
            parent=self,
            callback=on_files_dialog_dismissed,
        )

    def on_copy_all_clicked(self, button: Gtk.Button):
        if self.pref.notified_of_limit_breach():
            self.add_toast("<big>❌ Too many results to copy. Please use the Save button instead.</big>")
            return
        output = self.results_to_txt()
        clipboard = button.get_clipboard()
        clipboard.set(output)
        self.add_toast("<big>✅ Results copied to clipboard</big>")

    def on_save_clicked(self, widget):
        file_dialog = Gtk.FileDialog()
        file_dialog.set_title(title="Save")
        file_dialog.set_initial_name(name="results.txt")
        file_dialog.set_modal(modal=True)

        def on_file_dialog_dismissed(file_dialog: Gtk.FileDialog, gio_task):
            local_file = file_dialog.save_finish(gio_task)
            path: str = local_file.get_path()
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.results_to_txt())
                self.add_toast(f"<big>✅ Saved to <b>{path}</b></big>")
            except Exception as e:
                self.add_toast(f"<big>❌ Failed to save: {e}</big>")

        file_dialog.save(parent=self, callback=on_file_dialog_dismissed)

    def on_search_changed(self, entry: Gtk.SearchEntry, ui_list: Gtk.ListBox):
        self.search_query = entry.get_text().lower()
        ui_list.invalidate_filter()

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
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.logger = get_logger(self.__class__.__name__)
        self.create_action("quit", self.on_click_quit, shortcuts=["<Ctrl>Q"])
        self.create_action("set-recursive-mode", self.on_set_recursive_mode, GLib.VariantType.new("s"))
        self.create_action("show-searchbar", lambda *_: self.props.active_window.on_click_show_searchbar(), shortcuts=["<Ctrl>F"])

    def on_click_quit(self, *_):
        self.quit()

    def on_set_recursive_mode(self, action, param):
        win: MainWindow = self.props.active_window
        if win:
            state: bool = param.get_string() == "yes"
            win.pref.setting_gitignore.set_active(state)
            win.pref.setting_recursive.set_active(state)
            self.logger.info(f"Recursive mode set to {state} via action")

    def do_activate(self):
        self.logger.info(f"App {self.get_application_id()} activated")
        self.main_window: MainWindow = self.props.active_window
        if not self.main_window:
            self.main_window = MainWindow(self)
        self.main_window.present()

    def do_open(self, files, n_files, hint):
        self.logger.info(f"App {self.get_application_id()} opened with files ({n_files})")
        self.main_window: MainWindow = self.props.active_window
        if not self.main_window:
            self.main_window = MainWindow(self, files)
        else:
            self.main_window.start_job(files)
        self.main_window.present()

    def do_startup(self):
        Adw.Application.do_startup(self)

    def do_shutdown(self):
        self.logger.info("Shutting down...")
        self.main_window.cancel_event.set()
        Adw.Application.do_shutdown(self)

    def create_action(self, name, callback, parameter_type=None, shortcuts=None):
        action = Gio.SimpleAction.new(name=name, parameter_type=parameter_type)
        action.connect("activate", callback)
        self.add_action(action=action)
        if shortcuts:
            self.set_accels_for_action(
                detailed_action_name=f"app.{name}",
                accels=shortcuts,
            )


if __name__ == "__main__":
    try:
        app = Application()
        app.run(sys.argv)
    except KeyboardInterrupt:
        app.logger.info("App interrupted by user")
    finally:
        app.quit()
