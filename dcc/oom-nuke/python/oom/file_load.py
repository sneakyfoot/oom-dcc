import os, datetime

# Prefer PySide6 (Nuke 14+), fallback to PySide2
try:
    from PySide6 import QtWidgets, QtCore  # type: ignore
    def _dialog_exec(dlg):
        return dlg.exec()
except Exception:
    from PySide2 import QtWidgets, QtCore  # type: ignore
    def _dialog_exec(dlg):
        return dlg.exec_()
import nuke


# Helpers
def _script_modified():
    try:
        # Some Nuke versions expose a module-level function
        if hasattr(nuke, 'scriptModified'):
            return bool(nuke.scriptModified())
    except Exception:
        pass
    try:
        # Others provide nuke.modified()
        return bool(nuke.modified())
    except Exception:
        pass
    try:
        # Fallback: query the root node state
        return bool(nuke.root().modified())
    except Exception:
        return False
def _format_date(val):
    if not val:
        return ""
    if isinstance(val, datetime.datetime):
        return val.strftime("%Y-%m-%d %H:%M")

    for fmt in ("%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.datetime.strptime(str(val), fmt)
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass

    return str(val).split(".")[0][:16]


def _ensure_toolkit():
    # Try to reuse bootstrapped session from init.py, fallback to site bootstrap
    engine = getattr(nuke, 'oom_engine', None)
    tk = getattr(nuke, 'oom_tk', None)
    context = getattr(nuke, 'oom_context', None)

    if engine and tk and context:
        return engine, tk, tk.shotgun, context

    try:
        import oom_sg_tk  # noqa: F401
        from oom_bootstrap import bootstrap
        engine, tk, sg = bootstrap()
        # Best-effort: context from current script path
        path = nuke.root().name()
        try:
            context = tk.context_from_path(path) if path and os.path.isabs(path) else tk.context_empty()
        except Exception:
            context = tk.context_empty()
        nuke.oom_engine = engine
        nuke.oom_tk = tk
        nuke.oom_context = context
        return engine, tk, sg, context
    except Exception as e:
        raise RuntimeError(f"Toolkit bootstrap failed: {e}")


class VersionsDialog(QtWidgets.QDialog):
    def __init__(self, publishes, main_dialog=None, parent=None):
        super(VersionsDialog, self).__init__(parent)

        self.main_dialog = main_dialog

        self.setWindowTitle("Select Version")
        self.setMinimumWidth(400)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)

        layout = QtWidgets.QVBoxLayout(self)

        self.version_list = QtWidgets.QListWidget()
        layout.addWidget(self.version_list)

        self.open_btn = QtWidgets.QPushButton("Open Version")
        self.open_btn.clicked.connect(self.open_version)
        layout.addWidget(self.open_btn)

        self.publishes = publishes
        for pub in self.publishes:
            created = _format_date(pub.get("created_at"))
            label = f'v{pub["version_number"]:03d}  ({created})'
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, pub["path"]["local_path"])
            self.version_list.addItem(item)

    def open_version(self):
        item = self.version_list.currentItem()
        if not item:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Please select a version to open.")
            return

        path = item.data(QtCore.Qt.UserRole)
        try:
            if _script_modified():
                if not nuke.ask("Current script has unsaved changes. Continue?"):
                    return
            nuke.scriptOpen(path)
            print(f"[oom] Opened Nuke script: {path}")
            if self.main_dialog:
                self.main_dialog.close()
            self.accept()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Open Failed", f"Failed to open script:\n{e}")


def _main_window():
    try:
        return nuke.qt.mainWindow()  # Nuke helper returns QWidget
    except Exception:
        return QtWidgets.QApplication.activeWindow()


_OPEN_DIALOG_REF = None


class OpenDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(OpenDialog, self).__init__(parent)

        self.setWindowTitle("OOM Open Published Script")
        self.setMinimumWidth(420)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)

        self.engine, self.tk, self.sg, self.context = _ensure_toolkit()
        self.project = self.context.project
        self.entity = self.context.entity

        layout = QtWidgets.QVBoxLayout(self)

        # Step filter
        step_layout = QtWidgets.QHBoxLayout()
        step_layout.addWidget(QtWidgets.QLabel("Pipeline Step"))
        self.step_field = QtWidgets.QComboBox()
        step_layout.addWidget(self.step_field)
        layout.addLayout(step_layout)

        self.publish_list = QtWidgets.QListWidget()
        layout.addWidget(self.publish_list)

        button_layout = QtWidgets.QHBoxLayout()
        self.open_btn = QtWidgets.QPushButton("Open Latest")
        self.open_btn.clicked.connect(self.open_latest)
        self.versions_btn = QtWidgets.QPushButton("Versions...")
        self.versions_btn.clicked.connect(self.show_versions)
        button_layout.addWidget(self.open_btn)
        button_layout.addWidget(self.versions_btn)
        layout.addLayout(button_layout)

        self.populate_pipeline_steps()
        self.step_field.currentIndexChanged.connect(self.populate_publishes)
        self.populate_publishes()

    def populate_pipeline_steps(self):
        self.step_field.clear()
        self.step_field.addItem("All Steps", None)

        entity_type = self.entity["type"] if self.entity else None
        self.pipeline_steps = self.sg.find(
            "Step",
            [["entity_type", "is", entity_type]],
            ["code", "name"]
        ) if entity_type else []
        for step in self.pipeline_steps:
            self.step_field.addItem(step.get("code") or step.get("name"), step)

    def populate_publishes(self):
        self.publish_list.clear()
        if not (self.project and self.entity):
            return

        filters = [
            ["project", "is", self.project],
            ["entity", "is", self.entity],
            # Facility custom PublishedFileType for Nuke
            ["published_file_type.PublishedFileType.code", "is", "oom_nuke_file"],
        ]

        step = self.step_field.currentData() if hasattr(self, "step_field") else None
        if step:
            filters.append(["task.Task.step", "is", step])

        fields = ["code", "version_number", "path", "created_at"]
        publishes = self.sg.find(
            "PublishedFile", filters, fields,
            order=[{"field_name": "version_number", "direction": "desc"}]
        )

        grouped = {}
        for pub in publishes:
            grouped.setdefault(pub["code"], []).append(pub)

        self.grouped_publishes = grouped

        for code, items in grouped.items():
            latest = items[0]
            created = _format_date(latest.get("created_at"))
            label = f'{code}  v{latest["version_number"]:03d}  ({created})'
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, {"code": code, "publishes": items})
            self.publish_list.addItem(item)

    def open_latest(self):
        item = self.publish_list.currentItem()
        if not item:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Please select a file.")
            return

        data = item.data(QtCore.Qt.UserRole)
        publishes = data.get("publishes", [])
        if not publishes:
            QtWidgets.QMessageBox.critical(self, "Invalid Selection", "No publishes found for selection.")
            return

        latest = publishes[0]
        path = latest["path"]["local_path"]

        try:
            if _script_modified():
                if not nuke.ask("Current script has unsaved changes. Continue?"):
                    return
            nuke.scriptOpen(path)
            print(f"[oom] Opened Nuke script: {path}")
            self.close()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Open Failed", f"Failed to open script:\n{e}")

    def show_versions(self):
        item = self.publish_list.currentItem()
        if not item:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Please select a file.")
            return

        data = item.data(QtCore.Qt.UserRole)
        publishes = data.get("publishes", [])
        if not publishes:
            QtWidgets.QMessageBox.critical(self, "Invalid Selection", "No publishes found for selection.")
            return

        dlg = VersionsDialog(publishes, main_dialog=self, parent=self)
        _dialog_exec(dlg)


def launch():
    global _OPEN_DIALOG_REF
    try:
        dlg = OpenDialog(parent=_main_window())
        # keep reference so it isn't garbage-collected
        _OPEN_DIALOG_REF = dlg
        dlg.show()
        try:
            dlg.raise_()
            dlg.activateWindow()
        except Exception:
            pass
        print('[oom] OpenDialog launched')
    except Exception as e:
        nuke.message(f"[oom] Failed to launch OpenDialog:\n{e}")
