import os
import nuke

# Qt optional (for dialogs); prefer PySide6
try:
    from PySide6 import QtWidgets, QtCore  # type: ignore
except Exception:
    try:
        from PySide2 import QtWidgets, QtCore  # type: ignore
    except Exception:
        QtWidgets = None
        QtCore = None


def _dialog_exec(dlg):
    try:
        return dlg.exec()
    except Exception:
        return dlg.exec_()


def _format_date(val):
    try:
        import datetime

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
    except Exception:
        return str(val)[:16]


# Toolkit helpers
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


def _internal_read(node):
    try:
        return node.node("read1")
    except Exception:
        return None


def _set_file(node, path):
    read = _internal_read(node)
    if read is None:
        nuke.message('[oom] OOM_Read gizmo missing internal node "read1"')
        return False
    try:
        # Convert SG style frame tokens (e.g. %04d) to Nuke style (####)
        import re

        def _repl(m):
            try:
                w = int(m.group(1))
            except Exception:
                w = 4
            w = max(1, min(w, 8))
            return "#" * w

        if isinstance(path, str):
            path = re.sub(r"%0?(\d+)d", _repl, path)
            path = re.sub(r"%d", "####", path)
        read["file"].setValue(path)
        # Infer and apply frame range
        try:
            _apply_frame_range(read, path)
        except Exception:
            pass
        return True
    except Exception:
        return False


def _apply_frame_range(read_node, pattern):
    import re, glob

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
        if "first" in read_node.knobs():
            read_node["first"].setValue(start)
        if "last" in read_node.knobs():
            read_node["last"].setValue(end)
        if "use_limit" in read_node.knobs():
            read_node["use_limit"].setValue(True)
        try:
            read_node["reload"].execute()
        except Exception:
            pass
    except Exception:
        pass


def _query_publishes(pf_code, context, code=None):
    engine, tk, sg, ctx = _ensure_toolkit()
    proj = (context or ctx).project if (context or ctx) else None
    ent = (context or ctx).entity if (context or ctx) else None
    if not (proj and ent):
        return []
    filters = [
        ["project", "is", proj],
        ["entity", "is", ent],
        ["published_file_type.PublishedFileType.code", "is", pf_code],
    ]
    if code:
        filters.append(["code", "is", code])
    fields = ["code", "name", "version_number", "path"]
    pubs = sg.find(
        "PublishedFile",
        filters,
        fields,
        order=[{"field_name": "version_number", "direction": "desc"}],
    )
    return pubs


def update_to_latest(node):
    """Update gizmo's internal Read to the latest publish using current path.

    Derives the publish code from the internal Read's file path (no gizmo knobs).
    Searches across common image PublishedFileType codes.
    """
    rd = _internal_read(node)
    if not rd:
        nuke.message('[oom] OOM_Read gizmo missing internal node "read1"')
        return

    try:
        file_path = rd["file"].value()
    except Exception:
        file_path = ""

    if not file_path:
        nuke.tprint("[oom] No file set on internal Read; cannot derive code")
        return

    # Derive code similar to Houdini loader: parent of the file directory
    try:
        dir1 = os.path.dirname(file_path)
        code = os.path.basename(os.path.dirname(dir1))
        if not code or code in (".", "/"):  # fallback to basename without extension
            code = os.path.splitext(os.path.basename(file_path))[0]
    except Exception:
        code = os.path.splitext(os.path.basename(file_path))[0]

    # Query SG for latest across both image types
    try:
        engine, tk, sg, context = _ensure_toolkit()
        proj = context.project if context else None
        ent = context.entity if context else None
        if not (proj and ent):
            nuke.message("[oom] No context set to query ShotGrid")
            return
        try:
            import oom_sg_io

            latest = oom_sg_io.latest_for_code(
                sg,
                project=proj,
                entity=ent,
                published_file_types=(
                    "oom_renderpass",
                    "oom_comp",
                ),
                code=code,
                fields=["code", "version_number", "path"],
            )
        except Exception:
            pubs = _query_publishes(
                "oom_renderpass", context, code=code
            ) + _query_publishes("oom_comp", context, code=code)
            latest = pubs[0] if pubs else None
    except Exception as e:
        nuke.message(f"[oom] ShotGrid query failed: {e}")
        return

    if not latest:
        nuke.tprint(f"[oom] No publishes found for code {code}")
        return

    path = ((latest or {}).get("path") or {}).get("local_path")
    if path and _set_file(node, path):
        nuke.tprint(
            f"[oom] OOM_Read set latest v{latest.get('version_number')} for code {code}"
        )


def update_latest(node):
    """Alias for wiring directly to a gizmo button (no knob checks)."""
    update_to_latest(node)


def pick_and_apply(node):
    """Open a versions dialog for the current code/type and set the internal Read."""
    if QtWidgets is None:
        nuke.message("[oom] Qt not available for version picker")
        return
    pf_code = node["pf_type"].value() if "pf_type" in node.knobs() else "oom_renderpass"
    code = node["code"].value() if "code" in node.knobs() else None
    pubs = _query_publishes(pf_code, getattr(nuke, "oom_context", None), code=code)
    if not pubs:
        nuke.message("[oom] No publishes found")
        return

    # Lightweight inline versions dialog
    dlg = QtWidgets.QDialog()
    dlg.setWindowTitle("Select Image Version")
    dlg.setMinimumWidth(420)
    layout = QtWidgets.QVBoxLayout(dlg)
    listw = QtWidgets.QListWidget()
    layout.addWidget(listw)
    for p in pubs:
        key = p.get("code") or p.get("name")
        vn = p.get("version_number")
        it = QtWidgets.QListWidgetItem(f"{key}  v{vn:03d}")
        it.setData(QtCore.Qt.UserRole, p)
        listw.addItem(it)
    btn = QtWidgets.QPushButton("Apply Version")
    layout.addWidget(btn)

    def _apply():
        it = listw.currentItem()
        if not it:
            return
        pub = it.data(QtCore.Qt.UserRole)
        path = ((pub or {}).get("path") or {}).get("local_path")
        if path and _set_file(node, path):
            node["version"].setValue(int(pub.get("version_number") or 0))
            dlg.accept()

    btn.clicked.connect(_apply)
    _dialog_exec(dlg)


def knob_changed():
    """Entry point for gizmo knobChanged script.

    Wire this from the gizmo's knobChanged with:
      python {import oom.nodes.read_gizmo as g; g.knob_changed()}
    """
    try:
        n = nuke.thisNode()
        k = nuke.thisKnob()
    except Exception:
        return

    # Never mutate during renders
    try:
        if getattr(nuke, "executing", lambda: False)():
            return
    except Exception:
        pass

    # Update path on relevant knob edits
    if k.name() in ("code", "pf_type") and n["force_latest"].value():
        update_to_latest(n)


# ---------------------------------------------------------------------------
# Houdini-like browser for gizmo (Sequence/Shot/Step/Type filters)


class _GizmoVersionsDialog(QtWidgets.QDialog):
    def __init__(self, gizmo_node, publishes, parent=None):
        super(_GizmoVersionsDialog, self).__init__(parent)
        self.gizmo_node = gizmo_node
        self.setWindowTitle("Select Version")
        self.setMinimumWidth(420)
        layout = QtWidgets.QVBoxLayout(self)
        self.list = QtWidgets.QListWidget()
        layout.addWidget(self.list)
        self.apply_btn = QtWidgets.QPushButton("Apply Version")
        self.apply_btn.clicked.connect(self._apply)
        layout.addWidget(self.apply_btn)
        for pub in publishes:
            created = _format_date(pub.get("created_at"))
            vn = pub.get("version_number")
            it = QtWidgets.QListWidgetItem(f"v{vn:03d}  ({created})")
            it.setData(QtCore.Qt.UserRole, pub)
            self.list.addItem(it)

    def _apply(self):
        it = self.list.currentItem()
        if not it:
            return
        pub = it.data(QtCore.Qt.UserRole)
        path = ((pub or {}).get("path") or {}).get("local_path")
        if path and _set_file(self.gizmo_node, path):
            self.accept()


class _GizmoBrowseDialog(QtWidgets.QDialog):
    IMAGE_PUBLISHED_TYPES = ("oom_renderpass", "oom_comp")

    def __init__(self, gizmo_node, parent=None):
        super(_GizmoBrowseDialog, self).__init__(parent)
        self.gizmo_node = gizmo_node
        self.setWindowTitle("Browse Image Publish")
        self.setMinimumWidth(560)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)

        self.engine, self.tk, self.sg, self.context = _ensure_toolkit()
        self.project = self.context.project if self.context else None
        self.entity = self.context.entity if self.context else None

        layout = QtWidgets.QVBoxLayout(self)

        # Sequence / Shot selectors
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

        # Step selector
        step_layout = QtWidgets.QHBoxLayout()
        step_layout.addWidget(QtWidgets.QLabel("Pipeline Step"))
        self.step_field = QtWidgets.QComboBox()
        step_layout.addWidget(self.step_field)
        layout.addLayout(step_layout)

        # Type selector with All Types
        type_layout = QtWidgets.QHBoxLayout()
        type_layout.addWidget(QtWidgets.QLabel("Type"))
        self.type_field = QtWidgets.QComboBox()
        self._type_codes = list(self.IMAGE_PUBLISHED_TYPES)
        self.type_field.addItem("All Types", None)
        for code in self._type_codes:
            self.type_field.addItem(
                code.replace("oom_", "").replace("_", " ").title(), code
            )
        type_layout.addWidget(self.type_field)
        layout.addLayout(type_layout)

        # Publish list
        self.publish_list = QtWidgets.QListWidget()
        layout.addWidget(self.publish_list)

        # Buttons
        btns = QtWidgets.QHBoxLayout()
        self.load_btn = QtWidgets.QPushButton("Load Latest")
        self.load_btn.clicked.connect(self.load_latest)
        self.versions_btn = QtWidgets.QPushButton("Versions...")
        self.versions_btn.clicked.connect(self.show_versions)
        btns.addWidget(self.load_btn)
        btns.addWidget(self.versions_btn)
        layout.addLayout(btns)

        # Wire and initial populate
        self._init_context_selectors()
        self.populate_pipeline_steps()
        self.seq_field.currentIndexChanged.connect(self._on_seq_changed)
        self.shot_field.currentIndexChanged.connect(self.populate_publishes)
        self.step_field.currentIndexChanged.connect(self.populate_publishes)
        self.type_field.currentIndexChanged.connect(self.populate_publishes)
        self.populate_publishes()

    # Helpers
    def _find_index_by_entity(self, combo, entity):
        if not entity:
            return -1
        t = entity.get("type")
        i = entity.get("id")
        for idx in range(combo.count()):
            data = combo.itemData(idx)
            if isinstance(data, dict) and data.get("type") == t and data.get("id") == i:
                return idx
        return -1

    def _sg_find_current_shot(self):
        if not self.entity or self.entity.get("type") != "Shot":
            return None
        return self.sg.find_one(
            "Shot",
            [["id", "is", self.entity["id"]]],
            ["code", "sg_sequence", "project"],
        )

    def _init_context_selectors(self):
        self._current_shot = self._sg_find_current_shot()
        self._current_seq = (
            self._current_shot.get("sg_sequence") if self._current_shot else None
        )
        self.populate_sequences()
        self.populate_shots()
        if self._current_seq:
            idx = self._find_index_by_entity(self.seq_field, self._current_seq)
            if idx != -1:
                self.seq_field.setCurrentIndex(idx)
        if self._current_shot:
            idx = self._find_index_by_entity(self.shot_field, self._current_shot)
            if idx != -1:
                self.shot_field.setCurrentIndex(idx)

    def populate_sequences(self):
        self.seq_field.clear()
        seqs = self.sg.find(
            "Sequence",
            [["project", "is", self.project]],
            ["code"],
            order=[{"field_name": "code", "direction": "asc"}],
        )
        for seq in seqs:
            label = seq.get("code") or f"Sequence {seq['id']}"
            self.seq_field.addItem(label, seq)

    def populate_shots(self):
        self.shot_field.clear()
        filters = [["project", "is", self.project]]
        sel_seq = self.seq_field.currentData()
        if sel_seq:
            filters.append(["sg_sequence", "is", sel_seq])
        shots = self.sg.find(
            "Shot",
            filters,
            ["code", "sg_sequence"],
            order=[{"field_name": "code", "direction": "asc"}],
        )
        for shot in shots:
            label = shot.get("code") or f"Shot {shot['id']}"
            self.shot_field.addItem(label, shot)

    def populate_pipeline_steps(self):
        self.step_field.clear()
        self.step_field.addItem("All Steps", None)
        entity_type = self.entity.get("type") if self.entity else None
        steps = (
            self.sg.find("Step", [["entity_type", "is", entity_type]], ["code", "name"])
            if entity_type
            else []
        )
        for step in steps:
            self.step_field.addItem(step.get("code") or step.get("name"), step)

    def _on_seq_changed(self):
        self.populate_shots()
        self.populate_publishes()

    def populate_publishes(self):
        self.publish_list.clear()
        selected_shot = self.shot_field.currentData()
        target_entity = selected_shot or self.entity
        filters = [["project", "is", self.project], ["entity", "is", target_entity]]
        sel_code = self.type_field.currentData()
        if sel_code:
            filters.append(
                ["published_file_type.PublishedFileType.code", "is", sel_code]
            )
        else:
            filters.append(
                [
                    "published_file_type.PublishedFileType.code",
                    "in",
                    list(self._type_codes),
                ]
            )
        step = self.step_field.currentData()
        if step:
            filters.append(["task.Task.step", "is", step])
        pubs = self.sg.find(
            "PublishedFile",
            filters,
            ["code", "version_number", "path", "created_at"],
            order=[{"field_name": "version_number", "direction": "desc"}],
        )
        grouped = {}
        for pub in pubs:
            grouped.setdefault(pub.get("code"), []).append(pub)
        for code, items in grouped.items():
            latest = items[0]
            label = f"{code}  v{latest.get('version_number'):03d}  ({_format_date(latest.get('created_at'))})"
            it = QtWidgets.QListWidgetItem(label)
            it.setData(QtCore.Qt.UserRole, {"code": code, "publishes": items})
            self.publish_list.addItem(it)

    def load_latest(self):
        it = self.publish_list.currentItem()
        if not it:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Select a file.")
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
        if path and _set_file(self.gizmo_node, path):
            try:
                self.gizmo_node["code"].setValue(str(data.get("code") or ""))
            except Exception:
                pass
            self.accept()

    def show_versions(self):
        it = self.publish_list.currentItem()
        if not it:
            QtWidgets.QMessageBox.warning(self, "No Selection", "Select a file.")
            return
        data = it.data(QtCore.Qt.UserRole) or {}
        pubs = data.get("publishes") or []
        if not pubs:
            QtWidgets.QMessageBox.critical(
                self, "Invalid Selection", "No publishes found."
            )
            return
        dlg = _GizmoVersionsDialog(self.gizmo_node, pubs, parent=self)
        _dialog_exec(dlg)


def browse_and_apply(node):
    if QtWidgets is None:
        nuke.message("[oom] Qt not available for browser")
        return
    dlg = _GizmoBrowseDialog(node)
    _dialog_exec(dlg)
