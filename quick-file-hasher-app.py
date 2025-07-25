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

APP_ID = "com.github.dd-se.quick-file-hasher"
APP_VERSION = "0.9.65"

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

Adw.init()
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
        if (caller == 1) or (caller == 2 and any(f.is_directory() for f in files)):
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
        self.set_title(title="Preferences")

        self.load_config_file()

        preference_page = Adw.PreferencesPage()
        self.add(preference_page)

        preference_group = Adw.PreferencesGroup()
        preference_group.set_description(description="Configure how files and folders are processed")
        preference_page.add(group=preference_group)

        self.setting_recursive = Adw.SwitchRow()
        self.setting_recursive.add_prefix(widget=Gtk.Image.new_from_icon_name(icon_name="edit-find-symbolic"))
        self.setting_recursive.set_title(title="Recursive Traversal")
        self.setting_recursive.set_subtitle(subtitle="Enable to process all files in subdirectories")
        self.setting_recursive.set_active(self.config["recursive_mode"])
        self.setting_recursive.connect("notify::active", self.on_switch_row_changed, "recursive_mode")
        preference_group.add(child=self.setting_recursive)

        self.setting_gitignore = Adw.SwitchRow()
        self.setting_gitignore.add_prefix(widget=Gtk.Image.new_from_icon_name(icon_name="action-unavailable-symbolic"))
        self.setting_gitignore.set_title(title="Respect .gitignore")
        self.setting_gitignore.set_subtitle(subtitle="Skip files and folders listed in .gitignore file")
        self.setting_gitignore.set_active(self.config["respect_gitignore"])
        self.setting_gitignore.connect("notify::active", self.on_switch_row_changed, "respect_gitignore")
        preference_group.add(child=self.setting_gitignore)

        preference_group_2 = Adw.PreferencesGroup()
        preference_group_2.set_description(description="Configure how results are saved")
        preference_page.add(group=preference_group_2)

        self.setting_save_errors = Adw.SwitchRow()
        self.setting_save_errors.add_prefix(widget=Gtk.Image.new_from_icon_name(icon_name="dialog-error-symbolic"))
        self.setting_save_errors.set_title(title="Save errors")
        self.setting_save_errors.set_subtitle(subtitle="Save errors to results file")
        self.setting_save_errors.set_active(self.config["save_errors"])
        self.setting_save_errors.connect("notify::active", self.on_save_errors_toggled)
        self.setting_save_errors.connect("notify::active", self.on_switch_row_changed, "save_errors")
        preference_group_2.add(child=self.setting_save_errors)

        preference_group_3 = Adw.PreferencesGroup()
        preference_group_3.set_description(description="Configure hashing behavior")
        preference_page.add(group=preference_group_3)

        self.setting_max_workers = Adw.SpinRow.new(Gtk.Adjustment.new(4, 1, 16, 1, 5, 0), 1, 0)
        self.setting_max_workers.set_editable(True)
        self.setting_max_workers.set_numeric(True)
        self.setting_max_workers.add_prefix(widget=Gtk.Image.new_from_icon_name(icon_name="process-working-symbolic"))
        self.setting_max_workers.set_title(title="Max Workers")
        self.setting_max_workers.set_subtitle(subtitle="Set how many files are hashed in parallel")
        self.setting_max_workers.set_value(self.config["max_workers"])
        self.setting_max_workers.connect("notify::value", self.on_spin_row_changed, "max_workers")
        preference_group_3.add(child=self.setting_max_workers)

        self.drop_down_algo_button = Adw.ComboRow()
        self.drop_down_algo_button.add_prefix(Gtk.Image.new_from_icon_name("dialog-password-symbolic"))
        self.available_algorithms = sorted(hashlib.algorithms_guaranteed)
        self.drop_down_algo_button.set_model(Gtk.StringList.new(self.available_algorithms))
        self.drop_down_algo_button.set_title("Hashing Algorithm")
        self.drop_down_algo_button.set_subtitle("Select the default hashing algorithm for new jobs")
        self.drop_down_algo_button.set_selected(self.available_algorithms.index(self.config["default_hash_algorithm"]))
        self.drop_down_algo_button.set_valign(Gtk.Align.CENTER)
        self.drop_down_algo_button.connect("notify::selected", self.on_algo_selected)
        preference_group_3.add(child=self.drop_down_algo_button)

        preference_group_4 = Adw.PreferencesGroup()
        preference_page.add(group=preference_group_4)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        self.button_save_preferences = Gtk.Button(label="Persist")
        self.button_save_preferences.add_css_class("suggested-action")
        self.button_save_preferences.set_tooltip_text("Persist current preferences to config file")
        self.button_save_preferences.connect("clicked", lambda _: self.save_preferences_to_config_file())
        self.button_save_preferences.set_hexpand(True)
        button_box.append(self.button_save_preferences)

        self.button_reset_preferences = Gtk.Button(label="Reset")
        self.button_reset_preferences.add_css_class("destructive-action")
        self.button_reset_preferences.set_tooltip_text("Reset all preferences to default values")
        self.button_reset_preferences.connect("clicked", lambda _: self.reset_preferences())
        self.button_reset_preferences.set_hexpand(True)
        button_box.append(self.button_reset_preferences)

        preference_group_4.add(child=button_box)

        self.process_env_variables()
        self._initialized = True

    def load_config_file(self):
        self.config = DEFAULTS.copy()
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    user_settings = json.load(f)
                self.config.update(user_settings)
                self.logger.debug(f"Loaded settings from {CONFIG_FILE}")
            else:
                self.logger.debug("Config file not found. Creating one with default settings.")
                self.save_preferences_to_config_file()

        except json.JSONDecodeError as e:
            self.logger.error(f"Error decoding JSON from {CONFIG_FILE}: {e}. Using defaults.")

        except Exception as e:
            self.logger.error(f"Unexpected error loading config from {CONFIG_FILE}: {e}. Using defaults.")

    def save_preferences_to_config_file(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, sort_keys=True)
            self.add_toast(Adw.Toast(title="<big>Success!</big>", use_markup=True, timeout=1))
            self.logger.info(f"Preferences persisted to file: {CONFIG_FILE}")

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

    def on_save_errors_toggled(self, row: Adw.SwitchRow, param: GObject.ParamSpec):
        self.get_root().has_results()


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


class QueueUpdateHandler(Queue):
    def __init__(self, maxsize=0):
        super().__init__(maxsize)
        self.logger = get_logger(self.__class__.__name__)

    def __iter__(self):
        while not self.empty():
            yield self.get_nowait()

    def update_progress(self, bytes_read: int, total_bytes: int):
        progress = min(bytes_read / total_bytes, 1.0)
        self.put(("progress", progress))

    def update_result(self, file: Path, hash_value: str, algo: str):
        self.put(("result", file, hash_value, algo))

    def update_error(self, file: Path, error: str):
        self.put(("error", file, error))

    def reset(self):
        while not self.empty():
            try:
                self.get_nowait()
            except Exception:
                break


class CalculateHashes:
    def __init__(
        self,
        preferences: "Preferences",
        queue: QueueUpdateHandler,
        event: threading.Event,
    ):
        self.logger = get_logger(self.__class__.__name__)
        self.pref = preferences
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


class HashRow(Adw.ActionRow):
    MAX_ROWS = Preferences().config["max_visible_results"]
    MAX_WIDTH_LABEL = max(len(algo) for algo in hashlib.algorithms_guaranteed)
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
        main_window: MainWindow = self.get_root()
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

            main_window.has_results()

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
        self.hash_name.set_width_chars(self.MAX_WIDTH_LABEL)
        self.prefix_hash_box.append(self.hash_name)

        self.add_prefix(self.prefix_hash_box)

        self.button_make_hashes = Gtk.Button()
        self.button_make_hashes.set_child(Gtk.Label(label="Multi-Hash"))
        self.button_make_hashes.set_valign(Gtk.Align.CENTER)
        self.button_make_hashes.set_tooltip_text("Calculate all available hash types for this file")
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

        # Hide the row if the counter exceeds MAX_ROWS
        exceeded_limit = self.get_counter() > self.MAX_ROWS
        self.set_hidden_result(exceeded_limit)

    def __str__(self):
        return f"{self.path}:{self.hash_value}:{self.algo}"

    def on_click_make_hashes(self, button: Gtk.Button):
        available_algorithms = Preferences().available_algorithms
        paths = [self.path] * (len(available_algorithms) - 1)
        hashes = [a for a in available_algorithms if a != self.algo]

        main_window: MainWindow = button.get_root()
        main_window.start_job(paths, hashes)

    def on_copy_clicked(self, button: Gtk.Button):
        button.set_sensitive(False)
        button.get_clipboard().set(self.hash_value)
        original_child = button.get_child()
        button.set_child(Gtk.Label(label="Copied!"))
        GLib.timeout_add(1500, lambda: (button.set_child(original_child), button.set_sensitive(True)))

    def on_compare_clicked(self, button: Gtk.Button):
        def handle_clipboard_comparison(clipboard, result):
            main_window: MainWindow = button.get_root()
            try:
                self.button_compare.set_sensitive(False)
                clipboard_text: str = clipboard.read_text_finish(result).strip()
                if clipboard_text == self.hash_value:
                    self.set_icon_("object-select-symbolic")
                    self.set_css_("success")
                    main_window.add_toast(f"<big>✅ Clipboard hash matches <b>{self.get_title()}</b>!</big>")
                else:
                    self.set_icon_("dialog-error-symbolic")
                    self.set_css_("error")
                    main_window.add_toast(f"<big>❌ The clipboard hash does <b>not</b> match <b>{self.get_title()}</b>!</big>")

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
                main_window.add_toast(f"<big>❌ Clipboard read error: {e}</big>")

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

    def __init__(self, app, paths: list[Path] | list[Gio.File] | None = None):
        super().__init__(application=app)
        self.logger = get_logger(self.__class__.__name__)
        self.set_default_size(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        self.set_size_request(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)

        self.pref = Preferences()
        self.queue_handler = QueueUpdateHandler()
        self.cancel_event = threading.Event()
        self.calculate_hashes = CalculateHashes(
            self.pref,
            self.queue_handler,
            self.cancel_event,
        )
        self.build_ui()
        self.setup_window_key_controller()
        if paths:
            self.start_job(paths)

    def setup_window_key_controller(self):
        window_key_controller = Gtk.EventControllerKey()
        window_key_controller.connect("key-pressed", self.on_window_key_pressed)
        self.add_controller(window_key_controller)

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

    def setup_main_content(self):
        self.main_content_overlay = Gtk.Overlay()

        self.spinner = Gtk.Spinner()
        self.spinner.set_size_request(100, 100)
        self.spinner.set_valign(Gtk.Align.CENTER)
        self.spinner.start()

        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        self.main_content_overlay.add_overlay(self.spinner)
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
        self.create_win_action("about", self.on_click_present_about_dialog)
        self.create_win_action("preferences", lambda *_: self.pref.present(self))
        self.button_menu = Gtk.MenuButton()
        self.button_menu.set_icon_name("open-menu-symbolic")
        self.button_menu.set_menu_model(self.menu)
        self.header_bar.pack_end(self.button_menu)

    def setup_progress_bar(self):
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_show_text(False)
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

        self.progress_bar.set_opacity(1.0)
        self.spinner.set_opacity(1.0)
        self.spinner.set_visible(True)

        self.button_cancel.set_visible(True)

        self.toolbar_view.set_content(self.main_content_overlay)

        self.processing_thread = threading.Thread(
            target=self.calculate_hashes,
            args=(
                paths,
                hashing_algorithm or self.pref.hashing_algorithm(),
            ),
            daemon=True,
        )
        self.processing_thread.start()
        GLib.timeout_add(50, self.process_queue, priority=GLib.PRIORITY_DEFAULT_IDLE)

    def process_queue(self):
        queue_empty = self.queue_handler.empty()
        job_done = self.progress_bar.get_fraction() == 1.0

        if self.cancel_event.is_set() or (queue_empty and job_done):
            self.processing_complete()
            return False

        iterations = 0
        while iterations < 100:
            try:
                update = self.queue_handler.get_nowait()
            except Empty:
                break

            kind = update[0]
            if kind == "progress":
                self.progress_bar.set_fraction(update[1])

            elif kind == "result":
                iterations += 1
                row = HashResultRow(*update[1:])
                self.ui_results.append(row)

            elif kind == "error":
                iterations += 1
                row = HashErrorRow(*update[1:])
                self.ui_errors.append(row)

        return True  # Continue monitoring

    def processing_complete(self):
        self.calculate_hashes.bytes_read = 0
        self.calculate_hashes.total_bytes = 0

        self.button_cancel.set_visible(False)
        self.hide_progress()

        GLib.timeout_add(500, self.has_results, priority=GLib.PRIORITY_DEFAULT)

    def hide_progress(self):
        self.animate_opacity(self.progress_bar, 1, 0, 500)
        self.animate_opacity(self.spinner, 1, 0, 500)
        GLib.timeout_add(1000, self.progress_bar.set_fraction, 0.0, priority=GLib.PRIORITY_DEFAULT)
        GLib.timeout_add(1000, self.spinner.set_visible, False, priority=GLib.PRIORITY_DEFAULT)
        GLib.timeout_add(1000, self.scroll_to_bottom, priority=GLib.PRIORITY_DEFAULT)

    def notify_limit_breach(self):
        hash_result_row_count = HashResultRow.get_counter()

        if hash_result_row_count > HashResultRow.MAX_ROWS and self.pref.notified_of_limit_breach() is False:
            self.add_toast(
                "<big>⚠️ Too many results! New results are now hidden from display for performance reasons.</big>",
                timeout=5,
                priority=Adw.ToastPriority.HIGH,
            )

            self.pref.set_notified_of_limit_breach(True)
            self.logger.debug(f"{hash_result_row_count} > {HashResultRow.MAX_ROWS}, hiding new results")

        elif hash_result_row_count <= HashResultRow.MAX_ROWS and self.pref.notified_of_limit_breach():
            self.add_toast(
                "<big>✅ Results are now visible again. Displaying all results.</big>",
                timeout=3,
                priority=Adw.ToastPriority.NORMAL,
            )

            self.pref.set_notified_of_limit_breach(False)
            self.logger.debug(f"{hash_result_row_count} < {HashResultRow.MAX_ROWS}, showing new results.")

        return hash_result_row_count > HashResultRow.MAX_ROWS

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

    def on_window_key_pressed(self, controller, keyval, keycode, state):
        if self.toolbar_view.get_content() is not self.main_content_overlay:
            return

        ctrl_pressed = state & Gdk.ModifierType.CONTROL_MASK
        if not self.search_entry.has_focus() and not ctrl_pressed:
            self.search_entry.set_visible(True)
            self.search_entry.grab_focus()

            if keyval == Gdk.KEY_Escape:
                self.search_entry.set_text("")
                self.search_entry.set_visible(False)

            elif keyval_to_unicode := Gdk.keyval_to_unicode(keyval):
                char = chr(keyval_to_unicode)
                self.search_entry.set_text(f"{self.search_entry.get_text()}{char if char.isprintable() else ''}")
                self.search_entry.set_position(-1)

    def on_click_present_about_dialog(self, *_):
        about_dialog = Adw.AboutDialog()
        about_dialog.set_application_name("Quick File Hasher")
        about_dialog.set_version(APP_VERSION)
        about_dialog.set_developer_name("Doğukan Doğru (dd-se)")
        about_dialog.set_license_type(Gtk.License(Gtk.License.MIT_X11))
        about_dialog.set_comments("A modern Nautilus extension and standalone GTK4/libadwaita app to calculate hashes.")
        about_dialog.set_website("https://github.com/dd-se/nautilus-extension-quick-file-hasher")
        about_dialog.set_issue_url("https://github.com/dd-se/nautilus-extension-quick-file-hasher/issues")
        about_dialog.set_copyright("© 2025 Doğukan Doğru (dd-se)")
        about_dialog.set_developers(["dd-se https://github.com/dd-se"])
        about_dialog.present(self)

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
        self.create_action("quit", self.on_click_quit)
        self.create_action("set-recursive-mode", self.on_set_recursive_mode, GLib.VariantType.new("s"))

    def on_click_quit(self, *_):
        self.quit()

    def on_set_recursive_mode(self, action, param):
        value: str = param.get_string()
        win: MainWindow = self.props.active_window
        if win:
            win.pref.setting_gitignore.set_active(value == "yes")
            win.pref.setting_recursive.set_active(value == "yes")
            self.logger.info(f"Recursive mode set to {value} via action")

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
