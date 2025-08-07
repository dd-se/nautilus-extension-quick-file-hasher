NAME = "Quick File Hasher"
APP = quick-file-hasher-app.py
APP_ID = $(shell grep -Po '^APP_ID\s*=\s*\K[^\s#]+' $(APP))
VERSION = $(shell grep -Po '^APP_VERSION\s*=\s*\K[^\s#]+' $(APP))
SHORTCUT_NAME = $(APP_ID).desktop
ICON_NAME = $(APP_ID).svg

INSTALL_DIR = $(HOME)/.local/bin
EXTENSION_DIR = $(HOME)/.local/share/nautilus-python/extensions
SHORTCUT_DIR = $(HOME)/.local/share/applications
ICON_DIR = $(HOME)/.local/share/icons/hicolor/scalable/apps

.PHONY: help makedir shortcut icon install uninstall symlink

help:
	@echo "Makefile for Quick File Hasher"
	@echo "Available commands:"
	@echo "  help       - Show this help message"
	@echo "  install    - Install the application"
	@echo "  uninstall  - Remove the application"

makedir:
	@mkdir -p $(INSTALL_DIR)
	@mkdir -p $(EXTENSION_DIR)
	@mkdir -p $(SHORTCUT_DIR)
	@mkdir -p $(ICON_DIR)

	@echo "Created directories: $(INSTALL_DIR), $(EXTENSION_DIR), $(SHORTCUT_DIR)"

shortcut:
	@echo "[Desktop Entry]" > $(SHORTCUT_NAME)
	@echo "Version=$(VERSION)" >> $(SHORTCUT_NAME)
	@echo "Name=$(NAME)" >> $(SHORTCUT_NAME)
	@echo "Comment=Python-based file hashing utility for Nautilus" >> $(SHORTCUT_NAME)
	@echo "Icon=$(ICON_NAME)" >> $(SHORTCUT_NAME)
	@echo "Exec=python3 $(INSTALL_DIR)/$(APP) --DESKTOP %U" >> $(SHORTCUT_NAME)
	@echo "Type=Application" >> $(SHORTCUT_NAME)
	@echo "Terminal=false" >> $(SHORTCUT_NAME)
	@echo "Categories=Utility;FileTools;" >> $(SHORTCUT_NAME)
	@echo "MimeType=all/all;" >> $(SHORTCUT_NAME)
	@echo "StartupNotify=true" >> $(SHORTCUT_NAME)
	@echo "Actions=Debug;" >> $(SHORTCUT_NAME)
	@echo "" >> $(SHORTCUT_NAME)

	@echo "[Desktop Action Debug]" >> $(SHORTCUT_NAME)
	@echo "Name=Run in Debug Mode" >> $(SHORTCUT_NAME)
	@echo "Exec=env LOGLEVEL=DEBUG python3 $(INSTALL_DIR)/$(APP) --DESKTOP %U" >> $(SHORTCUT_NAME)

	@echo "$(SHORTCUT_NAME) file created in current directory"

icon:
	@install -m 664 ./resources/icon.svg $(ICON_DIR)/$(ICON_NAME)

install: makedir shortcut icon
	@install -m 755 $(APP) $(INSTALL_DIR)
	@echo "Installed $(APP) to $(INSTALL_DIR)"

	@install -m 644 $(SHORTCUT_NAME) $(SHORTCUT_DIR)
	@echo "Installed desktop entry $(SHORTCUT_NAME) to $(SHORTCUT_DIR)"

	@ln -sf $(INSTALL_DIR)/$(APP) $(EXTENSION_DIR)/
	@echo "Symlink for $(APP) created in $(EXTENSION_DIR)"

	@rm -f $(SHORTCUT_NAME)
	@echo "Removed temporary .desktop file $(SHORTCUT_NAME)"

	@echo "Installation completed successfully"

uninstall:
	@rm -f $(INSTALL_DIR)/$(APP)
	@echo "Removed $(APP) from $(INSTALL_DIR)"

	@rm -f $(EXTENSION_DIR)/$(APP)
	@echo "Removed symlink from $(EXTENSION_DIR)"

	@rm -f $(SHORTCUT_DIR)/$(SHORTCUT_NAME)
	@echo "Removed desktop entry $(SHORTCUT_NAME) from $(SHORTCUT_DIR)"

	@rm -f $(ICON_DIR)/$(ICON_NAME)
	@echo "Removed application icon $(ICON_NAME) from $(ICON_DIR)"

	@echo "Uninstallation completed successfully"

symlink: makedir shortcut icon
	@ln -sf $(PWD)/$(APP) $(INSTALL_DIR)/
	@echo "Symlink for $(APP) created in $(INSTALL_DIR)"

	@ln -sf $(PWD)/$(APP) $(EXTENSION_DIR)/
	@echo "Symlink for $(APP) created in $(EXTENSION_DIR)"

	@install -m 644 $(SHORTCUT_NAME) $(SHORTCUT_DIR)
	@echo "Installed desktop entry $(SHORTCUT_NAME) to $(SHORTCUT_DIR)"

	@rm -f $(SHORTCUT_NAME)
	@echo "Removed temporary .desktop file $(SHORTCUT_NAME)"

	@echo "Installation completed successfully"
