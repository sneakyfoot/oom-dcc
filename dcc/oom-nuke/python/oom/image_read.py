import os
import nuke

# Prefer PySide6, fallback to PySide2
try:
    from PySide6 import QtWidgets, QtCore  # type: ignore
except Exception:
    from PySide2 import QtWidgets, QtCore  # type: ignore


def _ensure_toolkit():
    engine = getattr(nuke, "oom_engine", None)
    tk = getattr(nuke, "oom_tk", None)
    context = getattr(nuke, "oom_context", None)
    if engine and tk:
        return engine, tk, tk.shotgun, context
    try:
        import oom_sg_tk  # noqa: F401
        from oom_bootstrap import bootstrap

        engine, tk, sg = bootstrap()
        context = getattr(nuke, "oom_context", None) or tk.context_empty()
        nuke.oom_engine = engine
        nuke.oom_tk = tk
        nuke.oom_context = context
        return engine, tk, sg, context
    except Exception as e:
        raise RuntimeError(f"Toolkit bootstrap failed: {e}")


def _main_window():
    try:
        return nuke.qt.mainWindow()
    except Exception:
        return QtWidgets.QApplication.activeWindow()


def _nukeify_frame_tokens(path: str) -> str:
    import re

    if not path:
        return path

    # %04d, %4d -> #### (preserve width if provided)
    def _repl(m):
        width = m.group(1)
        try:
            w = int(width)
        except Exception:
            w = 4
        w = max(1, min(w, 8))  # sane bounds
        return "#" * w

    path = re.sub(r"%0?(\d+)d", _repl, path)
    # plain %d -> ####
    path = re.sub(r"%d", "####", path)
    return path


def _set_read_file(node, path):
    try:
        pattern = _nukeify_frame_tokens(path)
        node["file"].setValue(pattern)

        # Try to infer and apply frame range based on files on disk
        try:
            _apply_frame_range(node, pattern)
        except Exception:
            pass
    except Exception as e:
        nuke.message(f"[oom] Failed setting Read file: {e}")


def _apply_frame_range(node, pattern):
    import re, glob

    # Convert #### block to a capturing group
    m = re.search(r"(#+)", pattern)
    if not m:
        return
    hashes = m.group(1)
    width = len(hashes)
    regex = re.compile(
        re.escape(pattern).replace(re.escape(hashes), r"(\d{%d})" % width)
    )
    glob_pattern = pattern.replace(hashes, "*")
    files = glob.glob(glob_pattern)
    frames = []
    for f in files:
        mm = regex.match(f)
        if mm:
            try:
                frames.append(int(mm.group(1)))
            except Exception:
                pass
    if not frames:
        return
    start = min(frames)
    end = max(frames)
    try:
        if "first" in node.knobs():
            node["first"].setValue(start)
        if "last" in node.knobs():
            node["last"].setValue(end)
        if "use_limit" in node.knobs():
            node["use_limit"].setValue(True)
        # Best-effort reload
        try:
            node["reload"].execute()
        except Exception:
            pass
    except Exception:
        pass


class ReadVersionsDialog(QtWidgets.QDialog):
    def __init__(self, publishes, parent=None):
        super(ReadVersionsDialog, self).__init__(parent)
        self.setWindowTitle("Select Image Version")
        self.setMinimumWidth(480)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)

        self.publishes = publishes

        layout = QtWidgets.QVBoxLayout(self)
        self.list = QtWidgets.QListWidget()
        layout.addWidget(self.list)
        self.open_btn = QtWidgets.QPushButton("Create Read from Version")
        self.open_btn.clicked.connect(self._create)
        layout.addWidget(self.open_btn)

        for pub in self.publishes:
            vn = pub.get("version_number")
            code = pub.get("code") or pub.get("name")
            label = f"{code}  v{vn:03d}"
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, pub)
            self.list.addItem(item)

    def _create(self):
        item = self.list.currentItem()
        if not item:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Select a version.")
            return
        pub = item.data(QtCore.Qt.UserRole)
        path = ((pub or {}).get("path") or {}).get("local_path")
        if not path:
            QtWidgets.QMessageBox.critical(
                self, "Invalid Publish", "Missing local_path."
            )
            return
        node = nuke.createNode("Read", inpanel=False)
        _set_read_file(node, path)
        self.accept()


class InsertReadDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(InsertReadDialog, self).__init__(parent)
        self.setWindowTitle("Insert OOM Read")
        self.setMinimumWidth(540)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)

        self.engine, self.tk, self.sg, self.context = _ensure_toolkit()
        self.project = self.context.project if self.context else None
        self.entity = (self.context.entity if self.context else None) or {}

        layout = QtWidgets.QVBoxLayout(self)

        type_row = QtWidgets.QHBoxLayout()
        type_row.addWidget(QtWidgets.QLabel("Type"))
        self.type_combo = QtWidgets.QComboBox()
        # Facility publish types to browse
        self.type_combo.addItem("Render Pass", "oom_renderpass")
        self.type_combo.addItem("Comp Image", "oom_comp")
        type_row.addWidget(self.type_combo)
        layout.addLayout(type_row)

        self.list = QtWidgets.QListWidget()
        layout.addWidget(self.list)

        btn_row = QtWidgets.QHBoxLayout()
        self.create_btn = QtWidgets.QPushButton("Create Read (Latest)")
        self.create_btn.clicked.connect(self._create_latest)
        self.versions_btn = QtWidgets.QPushButton("Versions...")
        self.versions_btn.clicked.connect(self._open_versions)
        btn_row.addWidget(self.create_btn)
        btn_row.addWidget(self.versions_btn)
        layout.addLayout(btn_row)

        self.type_combo.currentIndexChanged.connect(self._refresh)
        self._refresh()

    def _refresh(self):
        self.list.clear()
        if not (self.project and self.entity):
            return
        pf_type = self.type_combo.currentData()
        # Prefer shared oom-core logic if available
        try:
            import oom_sg_io

            pubs = oom_sg_io.find_publishes(
                self.sg,
                project=self.project,
                entity=self.entity,
                published_file_types=pf_type,
                fields=["code", "name", "version_number", "path"],
            )
            grouped = oom_sg_io.group_by_code(pubs)
        except Exception:
            filters = [
                ["project", "is", self.project],
                ["entity", "is", self.entity],
                ["published_file_type.PublishedFileType.code", "is", pf_type],
            ]
            fields = ["code", "name", "version_number", "path"]
            pubs = self.sg.find(
                "PublishedFile",
                filters,
                fields,
                order=[{"field_name": "version_number", "direction": "desc"}],
            )
            grouped = {}
            for p in pubs:
                key = p.get("code") or p.get("name")
                grouped.setdefault(key, []).append(p)

        for key, items in grouped.items():
            latest = items[0]
            vn = latest.get("version_number")
            label = f"{key}  v{vn:03d}"
            it = QtWidgets.QListWidgetItem(label)
            it.setData(QtCore.Qt.UserRole, {"code": key, "publishes": items})
            self.list.addItem(it)

    def _create_latest(self):
        it = self.list.currentItem()
        if not it:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Select an item.")
            return
        data = it.data(QtCore.Qt.UserRole) or {}
        pubs = data.get("publishes") or []
        if not pubs:
            QtWidgets.QMessageBox.critical(
                self, "Invalid Selection", "No publishes found."
            )
            return
        latest = pubs[0]
        path = ((latest or {}).get("path") or {}).get("local_path")
        if not path:
            QtWidgets.QMessageBox.critical(
                self, "Invalid Publish", "Missing local_path."
            )
            return
        node = nuke.createNode("Read", inpanel=False)
        _set_read_file(node, path)
        self.accept()

    def _open_versions(self):
        it = self.list.currentItem()
        if not it:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Select an item.")
            return
        data = it.data(QtCore.Qt.UserRole) or {}
        pubs = data.get("publishes") or []
        if not pubs:
            QtWidgets.QMessageBox.critical(
                self, "Invalid Selection", "No publishes found."
            )
            return
        dlg = ReadVersionsDialog(pubs, parent=self)
        dlg.setParent(_main_window(), QtCore.Qt.Window)
        dlg.exec()


# Commands
_DIALOG_REF = None


def insert_read_dialog():
    global _DIALOG_REF
    dlg = InsertReadDialog(parent=_main_window())
    _DIALOG_REF = dlg
    dlg.show()
    try:
        dlg.raise_()
        dlg.activateWindow()
    except Exception:
        pass


def update_selected_read_to_latest():
    """Update selected Read node to the latest version of its publish by name.

    Uses the node's basename as code key; falls back to leaving as-is if not found.
    """
    engine, tk, sg, context = _ensure_toolkit()
    proj = context.project if context else None
    ent = context.entity if context else None
    if not (proj and ent):
        nuke.message("[oom] No context set to query ShotGrid")
        return

    sel = nuke.selectedNode() if nuke.selectedNodes() else None
    if not sel or sel.Class() != "Read":
        nuke.message("[oom] Select a Read node to update")
        return

    # infer key from filename basename (without extension/version)
    try:
        file_path = sel["file"].value()
    except Exception:
        file_path = ""
    base = os.path.basename(file_path)
    key = os.path.splitext(base)[0]

    pubs = sg.find(
        "PublishedFile",
        [
            ["project", "is", proj],
            ["entity", "is", ent],
            ["code", "is", key],
        ],
        ["code", "version_number", "path"],
        order=[{"field_name": "version_number", "direction": "desc"}],
    )

    if not pubs:
        nuke.message(f"[oom] No publishes found for {key}")
        return

    latest = pubs[0]
    new_path = ((latest or {}).get("path") or {}).get("local_path")
    if not new_path:
        nuke.message("[oom] Latest publish missing path")
        return
    _set_read_file(sel, new_path)
    nuke.tprint(f"[oom] Updated Read to latest for key {key}")
