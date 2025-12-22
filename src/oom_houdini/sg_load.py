from PySide6 import QtWidgets, QtCore
import hou
import datetime
import os


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
    """Dialog to select a specific published file version."""

    def __init__(
        self, publishes, node, main_dialog=None, parent=None, title="Select Version"
    ):
        super(VersionsDialog, self).__init__(parent)

        self.node = node
        self.main_dialog = main_dialog

        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)

        layout = QtWidgets.QVBoxLayout(self)
        self.version_list = QtWidgets.QListWidget()
        layout.addWidget(self.version_list)
        self.open_btn = QtWidgets.QPushButton("Load Version")
        self.open_btn.clicked.connect(self.load_version)
        layout.addWidget(self.open_btn)

        for pub in publishes:
            created = _format_date(pub.get("created_at"))
            label = f"v{pub['version_number']:03d}  ({created})"
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, pub["path"]["local_path"])
            self.version_list.addItem(item)

    def load_version(self):
        item = self.version_list.currentItem()
        if not item:
            QtWidgets.QMessageBox.warning(
                self, "No Selection", "Please select a version to load."
            )
            return

        path = item.data(QtCore.Qt.UserRole)
        try:
            self.node.parm("filename").set(path)
            if self.main_dialog:
                self.main_dialog.close()
            self.accept()
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Load Failed", f"Failed to set filename:\n{e}"
            )


class BrowseDialog(QtWidgets.QDialog):
    """Dialog to browse and load the latest publishes.

    Supports a single PublishedFileType code (str) or multiple (list[str]).
    """

    def __init__(self, node, published_file_type, parent=None):
        super(BrowseDialog, self).__init__(parent)

        self.node = node
        self.published_file_type = published_file_type

        # Title reflects single or multiple types
        if isinstance(published_file_type, (list, tuple)):
            title_types = ", ".join(published_file_type)
        else:
            title_types = str(published_file_type)
        self.setWindowTitle(f"Browse {title_types} Publish")
        self.setMinimumWidth(400)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)

        self.tk = hou.session.oom_tk
        self.sg = self.tk.shotgun
        self.context = hou.session.oom_context
        self.project = self.context.project
        self.entity = self.context.entity

        layout = QtWidgets.QVBoxLayout(self)

        # Context selectors (Sequence / Shot)
        ctx_layout = QtWidgets.QHBoxLayout()

        ctx_layout.addWidget(QtWidgets.QLabel("Seq"))
        self.seq_field = QtWidgets.QComboBox()
        self.seq_field.setMinimumWidth(140)
        ctx_layout.addWidget(self.seq_field)

        ctx_layout.addSpacing(10)

        ctx_layout.addWidget(QtWidgets.QLabel("Shot"))
        self.shot_field = QtWidgets.QComboBox()
        self.shot_field.setMinimumWidth(160)
        ctx_layout.addWidget(self.shot_field)

        layout.addLayout(ctx_layout)

        # Pipeline Step selector
        step_layout = QtWidgets.QHBoxLayout()
        step_layout.addWidget(QtWidgets.QLabel("Pipeline Step"))
        self.step_field = QtWidgets.QComboBox()
        step_layout.addWidget(self.step_field)
        layout.addLayout(step_layout)

        # Published Type selector (only shown when multiple types are allowed)
        self.type_field = None
        self._type_codes = None

        if isinstance(self.published_file_type, (list, tuple)):
            type_layout = QtWidgets.QHBoxLayout()
            type_layout.addWidget(QtWidgets.QLabel("Type"))

            self.type_field = QtWidgets.QComboBox()

            # Keep an ordered list of type codes we expose
            self._type_codes = list(self.published_file_type)

            # Add an "All Types" option, then each code humanized
            self.type_field.addItem("All Types", None)
            for code in self._type_codes:
                label = self._humanize_type_code(code)
                self.type_field.addItem(label, code)

            type_layout.addWidget(self.type_field)
            layout.addLayout(type_layout)

        self.publish_list = QtWidgets.QListWidget()
        layout.addWidget(self.publish_list)

        button_layout = QtWidgets.QHBoxLayout()
        self.load_btn = QtWidgets.QPushButton("Load Latest")
        self.load_btn.clicked.connect(self.load_latest)
        self.versions_btn = QtWidgets.QPushButton("Versions...")
        self.versions_btn.clicked.connect(self.show_versions)
        button_layout.addWidget(self.load_btn)
        button_layout.addWidget(self.versions_btn)
        layout.addLayout(button_layout)

        # Bootstrap current context (seq/shot), steps, and publishes
        self._init_context_selectors()
        self.populate_pipeline_steps()

        # Connect change handlers
        self.seq_field.currentIndexChanged.connect(self._on_seq_changed)
        self.shot_field.currentIndexChanged.connect(self.populate_publishes)
        self.step_field.currentIndexChanged.connect(self.populate_publishes)
        if self.type_field is not None:
            self.type_field.currentIndexChanged.connect(self.populate_publishes)

        # Initial list
        self.populate_publishes()

    # Helpers ---------------------------------------------------------------

    def _humanize_type_code(self, code: str) -> str:
        """Turn a PublishedFileType code like 'oom_renderpass' into 'Renderpass'."""

        if not code:
            return ""

        val = code
        if val.startswith("oom_"):
            val = val[4:]
        val = val.replace("_", " ")
        return val.title()

    def _sg_find_current_shot(self):
        """Return the current Shot entity with sequence if context is a Shot."""

        if not self.entity or self.entity.get("type") != "Shot":
            return None

        fields = ["code", "sg_sequence", "project"]
        return self.sg.find_one("Shot", [["id", "is", self.entity["id"]]], fields)

    def _init_context_selectors(self):
        """Populate seq/shot selectors and default to current context."""

        # Identify current shot and its sequence (if we are in a Shot context)
        self._current_shot = self._sg_find_current_shot()
        self._current_seq = None

        if self._current_shot and self._current_shot.get("sg_sequence"):
            self._current_seq = self._current_shot["sg_sequence"]

        # Fill sequences first, then shots based on selected sequence
        self.populate_sequences()
        self.populate_shots()

        # Try to select current seq/shot if available
        if self._current_seq:
            idx = self._find_index_by_entity(self.seq_field, self._current_seq)
            if idx != -1:
                self.seq_field.setCurrentIndex(idx)

        if self._current_shot:
            idx = self._find_index_by_entity(self.shot_field, self._current_shot)
            if idx != -1:
                self.shot_field.setCurrentIndex(idx)

    def _find_index_by_entity(self, combo, entity):
        """Find combo index by matching entity id/type stored in item data."""

        if not entity:
            return -1

        target_type = entity.get("type")
        target_id = entity.get("id")

        for i in range(combo.count()):
            data = combo.itemData(i)
            if not isinstance(data, dict):
                continue
            if data.get("type") == target_type and data.get("id") == target_id:
                return i

        return -1

    def populate_pipeline_steps(self):
        self.step_field.clear()
        self.step_field.addItem("All Steps", None)

        # Show all Steps configured for this entity type in SG
        steps = self.sg.find(
            "Step", [["entity_type", "is", self.entity["type"]]], ["code", "name"]
        )
        for step in steps:
            self.step_field.addItem(step.get("code") or step.get("name"), step)

    def populate_sequences(self):
        """Populate sequence dropdown for the current project."""

        self.seq_field.clear()

        # Query all Sequences in the project
        sequences = self.sg.find(
            "Sequence",
            [["project", "is", self.project]],
            ["code"],
            order=[{"field_name": "code", "direction": "asc"}],
        )

        for seq in sequences:
            label = seq.get("code") or f"Sequence {seq['id']}"
            self.seq_field.addItem(label, seq)

    def populate_shots(self):
        """Populate shot dropdown based on selected sequence (or project-wide)."""

        self.shot_field.clear()

        selected_seq = self.seq_field.currentData()

        filters = [["project", "is", self.project]]
        if selected_seq:
            filters.append(["sg_sequence", "is", selected_seq])

        shots = self.sg.find(
            "Shot",
            filters,
            ["code", "sg_sequence"],
            order=[{"field_name": "code", "direction": "asc"}],
        )

        for shot in shots:
            label = shot.get("code") or f"Shot {shot['id']}"
            self.shot_field.addItem(label, shot)

    def _on_seq_changed(self):
        """When sequence changes, repopulate shots and refresh publishes."""

        self.populate_shots()
        self.populate_publishes()

    def populate_publishes(self):
        self.publish_list.clear()

        # Decide which entity to search on: selected Shot if any, otherwise current context entity
        selected_shot = self.shot_field.currentData()
        target_entity = selected_shot or self.entity

        filters = [
            ["project", "is", self.project],
            ["entity", "is", target_entity],
        ]

        # Allow either a single code or multiple codes with an optional UI filter
        if isinstance(self.published_file_type, (list, tuple)):
            selected_code = None
            if self.type_field is not None:
                selected_code = self.type_field.currentData()

            if selected_code:
                filters.append(
                    ["published_file_type.PublishedFileType.code", "is", selected_code]
                )
            else:
                filters.append(
                    [
                        "published_file_type.PublishedFileType.code",
                        "in",
                        list(self.published_file_type),
                    ]
                )
        else:
            filters.append(
                [
                    "published_file_type.PublishedFileType.code",
                    "is",
                    self.published_file_type,
                ]
            )
        step = self.step_field.currentData()
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

    def load_latest(self):
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
            self.node.parm("filename").set(path)
            self.close()
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Load Failed", f"Failed to set filename:\n{e}"
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

        # Build a friendly title for versions dialog
        if isinstance(self.published_file_type, (list, tuple)):
            t = ", ".join(self.published_file_type)
        else:
            t = str(self.published_file_type)

        dlg = VersionsDialog(
            publishes,
            node=self.node,
            main_dialog=self,
            parent=self,
            title=f"Select {t} Version",
        )
        dlg.setParent(hou.ui.mainQtWindow(), QtCore.Qt.Window)
        dlg.exec()


def browse_publish(kwargs: dict, published_file_type) -> None:
    """Callback for the Browse button on a loader HDA.

    ``published_file_type`` may be a str code or a list of codes.
    """
    node = kwargs.get("node")
    dlg = BrowseDialog(node, published_file_type)
    dlg.setParent(hou.ui.mainQtWindow(), QtCore.Qt.Window)
    dlg.show()


def update_to_latest(target, published_file_type, is_path=False) -> None:
    """Update the node to the latest publish when ``force_latest`` is on.

    ``published_file_type`` may be a str code or a list of codes.
    """
    if is_path:
        node = hou.node(target)
    else:
        kwargs = target
        node = kwargs.get("node")
    if node is None:
        return

    force_latest_parm = node.parm("force_latest")
    if not force_latest_parm or not force_latest_parm.eval():
        return

    # Current file path from the node
    path = node.evalParm("filename")
    if not path:
        return

    # ShotGrid API
    tk = hou.session.oom_tk
    sg = tk.shotgun
    context = hou.session.oom_context

    # Resolve the publish's entity by first narrowing on publish code, then
    # matching the exact local_path client-side (SG API doesn't allow filtering
    # by 'path' directly in queries).
    dir_path, _ = os.path.split(path)
    publish_name = os.path.basename(os.path.dirname(dir_path))

    current_publish = None
    type_filter = None
    if isinstance(published_file_type, (list, tuple)):
        type_filter = [
            "published_file_type.PublishedFileType.code",
            "in",
            list(published_file_type),
        ]
    else:
        type_filter = [
            "published_file_type.PublishedFileType.code",
            "is",
            published_file_type,
        ]

    candidates = sg.find(
        "PublishedFile",
        [
            ["project", "is", context.project],
            type_filter,
            ["code", "is", publish_name],
        ],
        ["entity", "code", "version_number", "path", "project"],
        order=[{"field_name": "version_number", "direction": "desc"}],
    )
    for pub in candidates:
        p = (pub.get("path") or {}).get("local_path")
        if p and os.path.normpath(p) == os.path.normpath(path):
            current_publish = pub
            break

    # Fallback if we can't resolve the publish by exact path match
    if not current_publish:
        current_publish = {
            "entity": context.entity,
            "code": publish_name,
            "project": context.project,
        }

    # Build filters to find the latest version for this publish name within the same entity
    latest_filters = [
        ["project", "is", current_publish.get("project", context.project)],
        ["entity", "is", current_publish["entity"]],
        type_filter,
        ["code", "is", current_publish["code"]],
    ]

    latest = sg.find(
        "PublishedFile",
        latest_filters,
        ["version_number", "path"],
        order=[{"field_name": "version_number", "direction": "desc"}],
    )

    if not latest:
        return

    latest_path = latest[0]["path"]["local_path"]
    if latest_path and latest_path != path:
        node.parm("filename").set(latest_path)
