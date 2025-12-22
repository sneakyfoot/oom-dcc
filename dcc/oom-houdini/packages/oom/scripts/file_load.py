from PySide6 import QtWidgets, QtCore
import hou
import datetime


def _format_date(val):
    """Return a short human friendly date string."""
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


class VersionsDialog(QtWidgets.QDialog):
    """Dialog to select a specific version of a publish."""

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

        # store publishes list sorted by version desc
        self.publishes = publishes
        for pub in self.publishes:
            created = _format_date(pub.get("created_at"))
            label = f"v{pub['version_number']:03d}  ({created})"
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, pub["path"]["local_path"])
            self.version_list.addItem(item)

    def open_version(self):
        item = self.version_list.currentItem()
        if not item:
            QtWidgets.QMessageBox.warning(
                self, "No Selection", "Please select a version to open."
            )
            return

        path = item.data(QtCore.Qt.UserRole)
        try:
            hou.hipFile.load(path)
            print(f"[oom] Opened HIP file: {path}")
            if self.main_dialog:
                self.main_dialog.close()
            self.accept()
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Open Failed", f"Failed to open HIP file:\n{e}"
            )


class OpenDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(OpenDialog, self).__init__(parent)

        self.setWindowTitle("OOM Open Published HIP")
        self.setMinimumWidth(400)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)

        self.tk = hou.session.oom_tk
        self.sg = self.tk.shotgun
        self.context = hou.session.oom_context
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

        # Show all Steps configured for this entity type in SG
        self.pipeline_steps = self.sg.find(
            "Step", [["entity_type", "is", self.entity["type"]]], ["code", "name"]
        )
        for step in self.pipeline_steps:
            self.step_field.addItem(step.get("code") or step.get("name"), step)

    def populate_publishes(self):
        self.publish_list.clear()
        filters = [
            ["project", "is", self.project],
            ["entity", "is", self.entity],
            ["published_file_type.PublishedFileType.code", "is", "Houdini Scene"],
        ]
        step = self.step_field.currentData() if hasattr(self, "step_field") else None
        if step:
            # SG-native: rely on Task->Step relationship only
            filters.append(["task.Task.step", "is", step])
        fields = ["code", "version_number", "path", "created_at"]
        publishes = self.sg.find(
            "PublishedFile",
            filters,
            fields,
            order=[{"field_name": "version_number", "direction": "desc"}],
        )

        grouped = {}
        for pub in publishes:
            grouped.setdefault(pub["code"], []).append(pub)

        self.grouped_publishes = grouped

        for code, items in grouped.items():
            latest = items[0]
            created = _format_date(latest.get("created_at"))
            label = f"{code}  v{latest['version_number']:03d}  ({created})"
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
            QtWidgets.QMessageBox.critical(
                self, "Invalid Selection", "No publishes found for selection."
            )
            return

        latest = publishes[0]
        path = latest["path"]["local_path"]

        try:
            hou.hipFile.load(path)
            print(f"[oom] Opened HIP file: {path}")
            self.close()
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Open Failed", f"Failed to open HIP file:\n{e}"
            )

    def show_versions(self):
        item = self.publish_list.currentItem()
        if not item:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Please select a file.")
            return

        data = item.data(QtCore.Qt.UserRole)
        publishes = data.get("publishes", [])
        if not publishes:
            QtWidgets.QMessageBox.critical(
                self, "Invalid Selection", "No publishes found for selection."
            )
            return

        dlg = VersionsDialog(publishes, main_dialog=self, parent=self)
        dlg.setParent(hou.ui.mainQtWindow(), QtCore.Qt.Window)
        dlg.exec()


def launch():
    dlg = OpenDialog()
    dlg.setParent(hou.ui.mainQtWindow(), QtCore.Qt.Window)
    dlg.show()


launch()
