APPNAME = "Quick File Hasher"
VERSION = "0.7.0"
EXTENSION = quick-file-hasher-app.py
SHORTCUT_NAME = com.github.dd-se.quick-file-hasher.desktop
INSTALL_DIR = $(HOME)/.local/share/nautilus-python/extensions
DESKTOP_DIR = $(HOME)/.local/share/applications


# Create .desktop file
shortcut:
	@echo "Creating .desktop file: $(SHORTCUT_NAME)"
	@echo "[Desktop Entry]" > $(SHORTCUT_NAME)
	@echo "Version=$(VERSION)" >> $(SHORTCUT_NAME)
	@echo "Name=$(APPNAME)" >> $(SHORTCUT_NAME)
	@echo "Comment=Python-based file hashing utility for Nautilus" >> $(SHORTCUT_NAME)
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
	@echo "Installation completed successfully"

uninstall:
	@rm -f $(INSTALL_DIR)/$(EXTENSION)
	@rm -f $(DESKTOP_DIR)/$(SHORTCUT_NAME)
	@echo "Uninstallation completed successfully"

symlink: shortcut
	@mkdir -p $(INSTALL_DIR)
	@mkdir -p $(DESKTOP_DIR)
	@ln -s $(PWD)/$(EXTENSION) $(INSTALL_DIR)/
	@install -m 644 $(SHORTCUT_NAME) $(DESKTOP_DIR)
	@rm -f $(SHORTCUT_NAME)
	@echo "Symlink installed successfully"
.PHONY: shortcut install uninstall symlink