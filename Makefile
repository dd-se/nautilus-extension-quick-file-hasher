NAME = "Quick File Hasher"
APP = quick-file-hasher-app.py

VERSION = $(shell grep -Po '^APP_VERSION\s*=\s*\K[^\s#]+' $(APP))
SHORTCUT_NAME = $(shell grep -Po '^APP_ID\s*=\s*\K[^\s#]+' $(APP)).desktop

INSTALL_DIR = $(HOME)/.local/bin
EXTENSION_DIR = $(HOME)/.local/share/nautilus-python/extensions
SHORTCUT_DIR = $(HOME)/.local/share/applications

.PHONY: shortcut install uninstall symlink makedir

makedir:
	@mkdir -p $(INSTALL_DIR)
	@mkdir -p $(EXTENSION_DIR)
	@mkdir -p $(SHORTCUT_DIR)
	@echo "Created directories: $(INSTALL_DIR), $(EXTENSION_DIR), $(SHORTCUT_DIR)"

shortcut:
	@echo "[Desktop Entry]" > $(SHORTCUT_NAME)
	@echo "Version=$(VERSION)" >> $(SHORTCUT_NAME)
	@echo "Name=$(NAME)" >> $(SHORTCUT_NAME)
	@echo "Comment=Python-based file hashing utility for Nautilus" >> $(SHORTCUT_NAME)
	@echo "Icon=document-properties-symbolic" >> $(SHORTCUT_NAME)
	@echo "Exec=python3 $(INSTALL_DIR)/$(APP) --DESKTOP %U"  >> $(SHORTCUT_NAME)
	@echo "Type=Application" >> $(SHORTCUT_NAME)
	@echo "Terminal=false" >> $(SHORTCUT_NAME)
	@echo "Categories=Utility;FileTools;" >> $(SHORTCUT_NAME)
	@echo "MimeType=all/all;" >> $(SHORTCUT_NAME)
	@echo "$(SHORTCUT_NAME) file created in current directory"


install: makedir shortcut
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

	@echo "Uninstallation completed successfully"

symlink: makedir shortcut
	@ln -sf $(PWD)/$(APP) $(INSTALL_DIR)/
	@echo "Symlink for $(APP) created in $(INSTALL_DIR)"

	@ln -sf $(PWD)/$(APP) $(EXTENSION_DIR)/
	@echo "Symlink for $(APP) created in $(EXTENSION_DIR)"

	@install -m 644 $(SHORTCUT_NAME) $(SHORTCUT_DIR)
	@echo "Installed desktop entry $(SHORTCUT_NAME) to $(SHORTCUT_DIR)"

	@rm -f $(SHORTCUT_NAME)
	@echo "Removed temporary .desktop file $(SHORTCUT_NAME)"

	@echo "Installation completed successfully"
