APPNAME = "Quick File Hasher"
EXTENSION = quick-file-hasher-app.py
VERSION = $(shell grep -Po '^APP_VERSION\s*=\s*\K[^\s#]+' $(EXTENSION))
SHORTCUT_NAME = $(shell grep -Po '^APP_ID\s*=\s*\K[^\s#]+' $(EXTENSION)).desktop
INSTALL_DIR = $(HOME)/.local/share/nautilus-python/extensions
DESKTOP_DIR = $(HOME)/.local/share/applications

shortcut:
	@echo "Creating .desktop file: $(SHORTCUT_NAME)"
	@echo "[Desktop Entry]" > $(SHORTCUT_NAME)
	@echo "Version=$(VERSION)" >> $(SHORTCUT_NAME)
	@echo "Name=$(APPNAME)" >> $(SHORTCUT_NAME)
	@echo "Comment=Python-based file hashing utility for Nautilus" >> $(SHORTCUT_NAME)
	@echo "Icon=document-properties" >> $(SHORTCUT_NAME)
	@echo "Exec=python3 $(INSTALL_DIR)/$(EXTENSION)" >> $(SHORTCUT_NAME)
	@echo "Type=Application" >> $(SHORTCUT_NAME)
	@echo "Terminal=false" >> $(SHORTCUT_NAME)
	@echo "Categories=Utility;FileTools;" >> $(SHORTCUT_NAME)
	@echo ".desktop file created in current directory"

install: shortcut
	@mkdir -p $(INSTALL_DIR)
	@mkdir -p $(DESKTOP_DIR)
	@install -m 755 $(EXTENSION) $(INSTALL_DIR)
	@install -m 644 $(SHORTCUT_NAME) $(DESKTOP_DIR)
	@rm -f $(SHORTCUT_NAME)
	@echo "Installed $(EXTENSION) to $(INSTALL_DIR)"
	@echo "Installed desktop entry $(SHORTCUT_NAME) to $(DESKTOP_DIR)"
	@echo "Installation completed successfully"

uninstall:
	@rm -f $(INSTALL_DIR)/$(EXTENSION)
	@rm -f $(DESKTOP_DIR)/$(SHORTCUT_NAME)
	@echo "Uninstallation completed successfully"

symlink: shortcut
	@mkdir -p $(INSTALL_DIR)
	@mkdir -p $(DESKTOP_DIR)
	@ln -sf $(PWD)/$(EXTENSION) $(INSTALL_DIR)/
	@install -m 644 $(SHORTCUT_NAME) $(DESKTOP_DIR)
	@rm -f $(SHORTCUT_NAME)
	@echo "Symlink for $(EXTENSION) created in $(INSTALL_DIR)"
	@echo "Installed desktop entry $(SHORTCUT_NAME) to $(DESKTOP_DIR)"
	@echo "Installation completed successfully"

.PHONY: shortcut install uninstall symlink