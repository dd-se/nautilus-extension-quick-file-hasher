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

APP_ID = "com.github.dd-se.quick-file-hasher"
APP_VERSION = "0.9.12"
APP_DEFAULT_HASHING_ALGORITHM = "sha256"

import hashlib
import logging
import os
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from queue import Queue
from typing import Callable, Literal

import gi  # type: ignore

gi.require_version(namespace="Gtk", version="4.0")
gi.require_version(namespace="Adw", version="1")
gi.require_version(namespace="Nautilus", version="4.0")

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Nautilus, Pango  # type: ignore

Adw.init()


css = b"""
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
css_provider.load_from_data(css)
Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def get_logger(name: str) -> logging.Logger:
    loglevel_str = os.getenv("LOGLEVEL", "INFO").upper()
    loglevel = getattr(logging, loglevel_str, logging.INFO)
    logger = logging.getLogger(name)
    logger.setLevel(loglevel)
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] %(levelname)-6s | %(funcName)-15s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
    return logger


logger = get_logger(__name__)


class AdwNautilusExtension(GObject.GObject, Nautilus.MenuProvider):
    def __init__(self):
        pass

    def nautilus_launch_app(self, menu_item: Nautilus.MenuItem, files: list[Nautilus.FileInfo], recursive_mode: bool = False):
        file_paths = [f.get_location().get_path() for f in files if f.get_location()]
        cmd = ["python3", Path(__file__).as_posix()] + file_paths
        env = None
        if recursive_mode:
            env = os.environ.copy()
            env["CH_RECURSIVE_MODE"] = "yes"
            os.system(f"gapplication action {APP_ID} set-recursive-mode \"'yes'\"")
        else:
            os.system(f"gapplication action {APP_ID} set-recursive-mode \"'no'\"")
        subprocess.Popen(cmd, env=env)
        logger.info(f"App {APP_ID} launched by file manager")

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
        else:
            menu = Nautilus.MenuItem(
                name=f"AdwNautilusExtension::OpenInAppNormal_{caller}",
                label="Calculate Hashes",
            )
            menu.connect("activate", self.nautilus_launch_app, files)
        return [menu]

    def get_background_items(self, current_folder: Nautilus.FileInfo) -> list[Nautilus.MenuItem]:
        if not current_folder.is_directory():
            return []
        return self.create_menu([current_folder], 1)

    def get_file_items(self, files: list[Nautilus.FileInfo]) -> list[Nautilus.MenuItem]:
        if not files:
            return []
        return self.create_menu(files, 2)


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
        if extend:
            rules = extend
        else:
            rules = [IgnoreRule(".git/", gitignore_path.parent)]

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


class CalculateHashes:
    def __init__(
        self,
        preferences: "Preferences",
        queue: Queue,
        event: threading.Event,
        zero_bytes_callback: Callable[[str], None],
    ):
        self.pref = preferences
        self.update_queue = queue
        self.cancel_event = event
        self.zero_bytes = zero_bytes_callback

    def __call__(self, paths: list[Path], algo: str):
        for i, path in enumerate(paths):
            try:
                if path.is_dir() and self.pref.respect_gitignore():
                    gitignore_file = path / ".gitignore"
                    rules = IgnoreRule.parse_gitignore(gitignore_file) if gitignore_file.exists() else []
                    paths[i] = (path, rules)
                    logger.debug(f"Rule count early: {len(paths[i][1])}")
                else:
                    paths[i] = (path, [])
            except Exception as e:
                paths[i] = (path, [])
                logger.exception(f"Error processing file: {e}")

        jobs = []
        total_bytes = 0

        def process_path(current_path: Path, current_rules: list[IgnoreRule]):
            nonlocal total_bytes
            if self.cancel_event.is_set():
                return

            if IgnoreRule.is_ignored(current_path, current_rules):
                logger.debug(f"Skipped late: {current_path}")
                return

            if current_path.is_file():
                total_bytes += current_path.stat().st_size
                jobs.append(current_path)

            elif current_path.is_dir() and self.pref.recursive_mode():
                local_rules = []
                if self.pref.respect_gitignore():
                    local_rules = current_rules.copy()
                    gitignore_file = current_path / ".gitignore"

                    if gitignore_file.exists():
                        IgnoreRule.parse_gitignore(gitignore_file, extend=local_rules)
                        logger.debug(f"Added rule late: {gitignore_file}")
                        logger.debug(f"Rule count late: {len(local_rules)}")

                for subpath in current_path.iterdir():
                    process_path(subpath, local_rules)
            else:
                # Raise error for invalid paths
                current_path.stat()

        for root_path, ignore_rules in paths:
            try:
                if root_path.is_dir():
                    for path in root_path.iterdir():
                        if IgnoreRule.is_ignored(path, ignore_rules):
                            logger.debug(f"Skipped early: {path}")
                            continue
                        process_path(path, ignore_rules)
                else:
                    process_path(root_path, ignore_rules)
            except Exception as e:
                logger.exception(f"Error processing file: {e}")
                self.update_queue.put(("error", root_path, str(e), algo))

        if total_bytes == 0:
            self.zero_bytes("<big>❌ No files found to process in the selected location.</big>")

        bytes_read = 0

        def hash_task(file: Path, shake_length: int = 32):
            nonlocal bytes_read
            if self.cancel_event.is_set():
                return
            if file.stat().st_size > 1024 * 1024 * 100:
                chunk_size = 1024 * 1024 * 4
            else:
                chunk_size = 1024 * 1024
            hash_obj = hashlib.new(algo)
            try:
                with open(file, "rb") as f:
                    while chunk := f.read(chunk_size):
                        if self.cancel_event.is_set():
                            return
                        hash_obj.update(chunk)
                        bytes_read += len(chunk)
                        self.update_queue.put(("progress", min(bytes_read / total_bytes, 1.0)))
                    self.update_queue.put(
                        (
                            "result",
                            file,
                            hash_obj.hexdigest(shake_length) if "shake" in algo else hash_obj.hexdigest(),
                            algo,
                        )
                    )
            except Exception as e:
                logger.exception(f"Error computing hash for file: {file.as_posix()}")
                self.update_queue.put(("error", str(file), str(e), algo))

        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(hash_task, jobs))


class HashResultRow(Adw.ActionRow):
    def __init__(self, path: Path, hash_value: str, hash_algorithm: str, **kwargs):
        super().__init__(**kwargs)
        self.path = path
        self.hash_value = hash_value
        self.algo = hash_algorithm

        self.set_title(GLib.markup_escape_text(self.path.as_posix()))
        self.set_subtitle(self.hash_value)
        self.set_subtitle_lines(1)
        self.set_title_lines(1)

        self.prefix_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.prefix_box.set_valign(Gtk.Align.CENTER)
        self.file_icon = Gtk.Image.new_from_icon_name("text-x-generic-symbolic")
        self.prefix_box.append(self.file_icon)
        self.prefix_box.append(Gtk.Label(label=self.algo.upper()))
        self.add_prefix(self.prefix_box)

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

    def __str__(self):
        return f"{self.path}:{self.hash_value}:{self.algo}"

    def on_click_make_hashes(self, button: Gtk.Button):
        main_window: MainWindow = button.get_root()
        for algo in main_window.available_algorithms:
            if algo != self.algo:
                main_window.start_job([self.path], algo)

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
                        self.set_css_classes(self.old_css),
                        self.set_icon_(self.old_file_icon_name),
                        self.button_compare.set_sensitive(True),
                    ),
                )
            except Exception as e:
                logger.exception(f"Error reading clipboard: {e}")
                main_window.add_toast(f"<big>❌ Clipboard read error: {e}</big>")

        clipboard = button.get_clipboard()
        clipboard.read_text_async(None, handle_clipboard_comparison)

    def on_delete_clicked(self, button: Gtk.Button):
        button.set_sensitive(False)
        parent: Gtk.ListBox = self.get_parent()
        main_window: MainWindow = self.get_root()
        parent.remove(self)
        if parent.get_first_child():
            main_window.update_badge_numbers()
        else:
            main_window.has_results()

    def set_icon_(
        self,
        icon_name: Literal[
            "text-x-generic-symbolic",
            "object-select-symbolic",
            "dialog-error-symbolic",
        ],
    ):
        self.old_file_icon_name = self.file_icon.get_icon_name()
        self.file_icon.set_from_icon_name(icon_name)

    def set_css_(self, css_class: Literal["success", "error"]):
        self.old_css = self.get_css_classes()
        self.add_css_class(css_class)

    def error(self):
        self.add_css_class("error")
        self.set_icon_("dialog-error-symbolic")
        self.button_copy_hash.set_tooltip_text("Copy error message to clipboard")
        self.button_compare.set_sensitive(False)
        self.button_make_hashes.set_sensitive(False)


class Preferences(Adw.PreferencesDialog):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title(title="Preferences")

        preference_page = Adw.PreferencesPage()
        self.add(preference_page)

        preference_group = Adw.PreferencesGroup()
        preference_group.set_description(description="Configure how files and folders are processed")
        preference_page.add(group=preference_group)

        self.setting_recursive = Adw.SwitchRow()
        self.setting_recursive.add_prefix(widget=Gtk.Image.new_from_icon_name(icon_name="edit-find-symbolic"))
        self.setting_recursive.set_title(title="Recursive Traversal")
        self.setting_recursive.set_subtitle(subtitle="Enable to process all files in subdirectories")
        preference_group.add(child=self.setting_recursive)

        self.setting_gitignore = Adw.SwitchRow()
        self.setting_gitignore.add_prefix(widget=Gtk.Image.new_from_icon_name(icon_name="action-unavailable-symbolic"))
        self.setting_gitignore.set_title(title="Respect .gitignore")
        self.setting_gitignore.set_subtitle(subtitle="Skip files and folders listed in .gitignore file")
        preference_group.add(child=self.setting_gitignore)

        if recursive_mode := bool(os.getenv("CH_RECURSIVE_MODE")):
            self.set_recursive_mode(recursive_mode)
            logger.info(f"Recursive mode set to {recursive_mode} via env variable")

    def set_recursive_mode(self, state: bool):
        self.setting_recursive.set_active(state)
        self.setting_gitignore.set_active(state)

    def recursive_mode(self):
        return self.setting_recursive.get_active()

    def respect_gitignore(self):
        return self.setting_gitignore.get_active()


class MainWindow(Adw.ApplicationWindow):
    DEFAULT_WIDTH = 970
    DEFAULT_HIGHT = 600
    algo: str = APP_DEFAULT_HASHING_ALGORITHM

    def __init__(self, app, paths: list[Path] | None = None):
        super().__init__(application=app)
        self.set_default_size(self.DEFAULT_WIDTH, self.DEFAULT_HIGHT)
        self.set_size_request(self.DEFAULT_WIDTH, self.DEFAULT_HIGHT)

        self.pref = Preferences()
        self.update_queue = Queue()
        self.cancel_event = threading.Event()
        self.calculate_hashes = CalculateHashes(
            self.pref,
            self.update_queue,
            self.cancel_event,
            lambda message: (self.add_toast(message), self.progress_bar.set_fraction(1.0)),
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

        self.available_algorithms = sorted(hashlib.algorithms_guaranteed)
        self.drop_down_algo_button = Gtk.DropDown.new_from_strings(self.available_algorithms)
        self.drop_down_algo_button.set_selected(self.available_algorithms.index(self.algo))
        self.drop_down_algo_button.set_valign(Gtk.Align.CENTER)
        self.drop_down_algo_button.set_tooltip_text("Choose hashing algorithm")
        self.drop_down_algo_button.connect("notify::selected-item", self.on_selected_item)
        self.first_top_bar_box.append(self.drop_down_algo_button)

        self.button_cancel = Gtk.Button(label="Cancel Job")
        self.button_cancel.add_css_class("destructive-action")
        self.button_cancel.set_valign(Gtk.Align.CENTER)
        self.button_cancel.set_visible(False)
        self.button_cancel.set_tooltip_text("Cancel the current operation")
        self.button_cancel.connect(
            "clicked",
            lambda _: (
                self.cancel_event.set(),
                self.add_toast("<big>❌ Job cancelled</big>"),
            ),
        )
        self.first_top_bar_box.append(self.button_cancel)

        self.spacer = Gtk.Box()
        self.spacer.set_hexpand(True)
        self.first_top_bar_box.append(self.spacer)

        self.setup_header_bar()
        self.first_top_bar_box.append(self.header_bar)

    def setup_second_top_bar(self):
        self.second_top_bar_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, margin_bottom=5)

        self.view_switcher = Adw.ViewSwitcher()
        self.view_switcher.set_sensitive(False)
        self.view_switcher.set_hexpand(True)
        self.view_switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        self.second_top_bar_box.append(self.view_switcher)

        self.spacer = Gtk.Box()
        self.spacer.set_hexpand(True)
        self.second_top_bar_box.append(self.spacer)

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

        def sort_by_hierarchy(row1: HashResultRow, row2: HashResultRow):
            """
            /folder/file_1\n
            /folder/file_2\n
            /folder/folder/file_1 ...
            """
            parts1 = row1.path.parts
            parts2 = row2.path.parts

            min_len = min(len(parts1), len(parts2))
            for i in range(min_len):
                if parts1[i] != parts2[i]:
                    path1_at_level = Path(*parts1[: i + 1])
                    path2_at_level = Path(*parts2[: i + 1])
                    is_dir1 = path1_at_level.is_dir()
                    is_dir2 = path2_at_level.is_dir()
                    # Files comes first at same level
                    if is_dir1 and not is_dir2:
                        return 1
                    if not is_dir1 and is_dir2:
                        return -1
                    # Same type, compare lexicographically
                    return -1 if parts1[i] < parts2[i] else 1
            # Identical
            return 0

        self.button_sort.connect(
            "clicked",
            lambda _: (
                self.ui_results.set_sort_func(sort_by_hierarchy),
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
                self.ui_results.remove_all(),
                self.ui_errors.remove_all(),
                self.has_results(),
                self.add_toast("<big>✅ Results cleared</big>"),
            ),
        )
        self.second_top_bar_box.append(self.button_clear)

        self.button_about = Gtk.Button(visible=False)
        self.button_about.set_valign(Gtk.Align.CENTER)
        self.button_about.connect("clicked", self.on_click_present_about_dialog)
        self.button_about_content = Adw.ButtonContent.new()
        self.button_about_content.set_icon_name(icon_name="help-about-symbolic")
        self.button_about_content.set_label(label="About")
        self.button_about_content.set_use_underline(use_underline=True)
        self.button_about.set_child(self.button_about_content)
        self.second_top_bar_box.append(self.button_about)

    def setup_header_bar(self):
        self.header_bar = Adw.HeaderBar()
        self.header_title_widget = Gtk.Label(label=f"<big><b>Calculate {self.algo.upper()} Hashes</b></big>", use_markup=True)
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
        self.ui_errors.set_filter_func(self.filter_func)
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
        self.progress_bar.set_visible(False)

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
                paths = [Path(f.get_path()) for f in files.get_files()]
                logger.debug(paths)
                action = Gdk.DragAction.COPY
            except Exception as e:
                action = 0
                self.add_toast(f"Drag & Drop failed: {e}")
            else:
                self.start_job(paths)
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

    def start_job(self, paths: list[Path], algo: str | None = None):
        self.cancel_event.clear()

        self.progress_bar.set_fraction(0.0)
        self.progress_bar.set_opacity(1.0)
        self.progress_bar.set_visible(True)

        self.spinner.set_opacity(1.0)
        self.spinner.set_visible(True)

        self.button_cancel.set_visible(True)
        self.button_select_files.set_sensitive(False)
        self.button_select_folders.set_sensitive(False)
        self.drop_down_algo_button.set_sensitive(False)

        self.toolbar_view.set_content(self.main_content_overlay)

        self.processing_thread = threading.Thread(target=self.calculate_hashes, args=(paths, algo or self.algo), daemon=True)
        self.processing_thread.start()
        GLib.timeout_add(100, self.process_queue, priority=GLib.PRIORITY_DEFAULT)
        GLib.timeout_add(100, self.check_processing_complete, priority=GLib.PRIORITY_DEFAULT)

    def process_queue(self):
        if self.cancel_event.is_set():
            return False  # Stop monitoring
        iterations = 0
        while not self.update_queue.empty() and iterations < 8:
            update = self.update_queue.get_nowait()
            if update[0] == "progress":
                _, progress = update
                self.progress_bar.set_fraction(progress)
            elif update[0] == "result":
                _, fname, hash_value, algo = update
                self.add_result(fname, hash_value, algo)
                iterations += 1
            elif update[0] == "error":
                _, fname, err, algo = update
                self.add_result(fname, err, algo, is_error=True)
                # self.add_toast(f"<big>❌ <b>{err}</b></big>")
                iterations += 1
            else:
                return False
        return True  # Continue monitoring

    def hide_progress(self):
        self.animate_opacity(self.progress_bar, 1.0, 0, 2000)
        self.animate_opacity(self.spinner, 1.0, 0, 2000)
        GLib.timeout_add(2000, self.spinner.set_visible, False, priority=GLib.PRIORITY_DEFAULT)
        GLib.timeout_add(100, self.scroll_to_bottom, priority=GLib.PRIORITY_DEFAULT)

    def check_processing_complete(self):
        if self.progress_bar.get_fraction() == 1.0 or self.cancel_event.is_set():
            self.button_cancel.set_visible(False)
            self.hide_progress()
            self.button_select_files.set_sensitive(True)
            self.button_select_folders.set_sensitive(True)
            self.drop_down_algo_button.set_sensitive(True)
            self.has_results()
            return False  # Stop monitoring
        return True  # Continue monitoring

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

    def add_result(self, file: Path, hash_value: str, algo: str, is_error: bool = False):
        row = HashResultRow(file, hash_value, algo)
        if is_error:
            self.ui_errors.append(row)
            row.error()
        else:
            self.ui_results.append(row)
        return row

    def animate_opacity(self, widget: Gtk.Widget, from_value: float, to_value: float, duration: int):
        animation = Adw.TimedAnimation.new(
            widget.get_parent(),
            from_value,
            to_value,
            duration,
            Adw.CallbackAnimationTarget.new(lambda opacity: widget.set_opacity(opacity)),
        )
        animation.play()

    def update_badge_numbers(self):
        self.results_stack_page.set_badge_number(sum(1 for _ in self.ui_results))
        self.errors_stack_page.set_badge_number(sum(1 for _ in self.ui_errors))

    def has_results(self, *signal_from_view_stack):
        has_results = self.ui_results.get_first_child() is not None
        has_errors = self.ui_errors.get_first_child() is not None
        current_page_name = self.view_stack.get_visible_child_name()

        self.button_save.set_sensitive(has_results or has_errors)
        self.button_copy_all.set_sensitive(has_results or has_errors)
        self.button_sort.set_sensitive(has_results)
        self.button_clear.set_sensitive(has_results or has_errors)
        self.update_badge_numbers()
        self.view_switcher.set_sensitive(has_results or has_errors)

        show_empty = (current_page_name == "results" and not has_results) or (current_page_name == "errors" and not has_errors)
        relevant_placeholder = self.empty_placeholder if current_page_name == "results" else self.empty_error_placeholder
        target = relevant_placeholder if show_empty else self.main_content_overlay
        if self.toolbar_view.get_content() is target and not signal_from_view_stack:
            return
        self.toolbar_view.set_content(target)
        Adw.TimedAnimation(
            widget=self,
            value_from=0.1,
            value_to=1.0,
            duration=500,
            target=Adw.CallbackAnimationTarget.new(lambda opacity: target.set_opacity(opacity)),
        ).play()

    def results_to_txt(self):
        results_text = "\n".join(str(r) for r in self.ui_results if self.filter_func(r))
        errors_text = "\n".join(str(r) for r in self.ui_errors if self.filter_func(r))
        output = ""
        now = datetime.now().strftime("%B %d, %Y at %I:%H:%M %Z")

        if results_text:
            output = f"Results - Saved on {now}:\n{'-' * 40}\n{results_text} {'\n\n' if errors_text else '\n'}"

        if errors_text:
            output = f"{output}Errors - Saved on {now}:\n{'-' * 40}\n{errors_text}\n"

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
                paths = [Path(f.get_path()) for f in files]
                logger.debug(paths)
                self.start_job(paths)

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
                paths = [Path(f.get_path()) for f in files]
                self.start_job(paths)

        file_dialog.select_multiple_folders(
            parent=self,
            callback=on_files_dialog_dismissed,
        )

    def on_copy_all_clicked(self, button: Gtk.Button):
        clipboard = button.get_clipboard()
        output = self.results_to_txt()
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

    def on_selected_item(self, drop_down: Gtk.DropDown, g_param_object):
        self.algo = drop_down.get_selected_item().get_string()
        self.header_title_widget.set_label(f"<big><b>Calculate {self.algo.upper()} Hashes</b></big>")

    def on_search_changed(self, entry: Gtk.SearchEntry, ui_list: Gtk.ListBox):
        self.search_query = entry.get_text().lower()
        ui_list.invalidate_filter()

    def filter_func(self, row: HashResultRow):
        terms = self.search_query.lower().split()
        return all(any(term in field for field in (row.path.as_posix().lower(), row.hash_value, row.algo.lower())) for term in terms)

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
        self.create_action("quit", self.on_click_quit)
        self.create_action("set-recursive-mode", self.on_set_recursive_mode, GLib.VariantType.new("s"))

    def on_click_quit(self, *_):
        self.quit()

    def on_set_recursive_mode(self, action, param):
        value: str = param.get_string()
        win: MainWindow = self.props.active_window
        if win and value.lower() in ("yes", "no"):
            win.pref.set_recursive_mode(value == "yes")
            logger.info(f"Recursive mode set to {value} via action")

    def do_activate(self):
        logger.info(f"App {self.get_application_id()} activated")
        self.main_window: MainWindow = self.props.active_window
        if not self.main_window:
            self.main_window = MainWindow(self)
        self.main_window.present()

    def do_open(self, files, n_files, hint):
        logger.info(f"App {self.get_application_id()} opened with files ({n_files})")
        paths = [Path(f.get_path()) for f in files if f.get_path()]
        self.main_window: MainWindow = self.props.active_window
        if not self.main_window:
            self.main_window = MainWindow(self, paths)
        else:
            self.main_window.start_job(paths)
        self.main_window.present()

    def do_startup(self):
        Adw.Application.do_startup(self)

    def do_shutdown(self):
        logger.info("Shutting down...")
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
        logger.info("App interrupted by user")
    finally:
        app.quit()
