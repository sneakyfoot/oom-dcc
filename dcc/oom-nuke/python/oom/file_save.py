import os, re

# Prefer PySide6 (Nuke 14+), fallback to PySide2
try:
    from PySide6 import QtWidgets, QtCore  # type: ignore
except Exception:
    from PySide2 import QtWidgets, QtCore  # type: ignore
import nuke


def _main_window():
    try:
        return nuke.qt.mainWindow()
    except Exception:
        return QtWidgets.QApplication.activeWindow()


_SAVE_DIALOG_REF = None


def _ensure_toolkit():
    engine = getattr(nuke, "oom_engine", None)
    tk = getattr(nuke, "oom_tk", None)
    context = getattr(nuke, "oom_context", None)

    if engine and tk and context:
        return engine, tk, tk.shotgun, context

    try:
        import oom_sg_tk  # noqa: F401
        from oom_bootstrap import bootstrap

        engine, tk, sg = bootstrap()
        # Best-effort empty context until saved
        context = tk.context_empty()
        nuke.oom_engine = engine
        nuke.oom_tk = tk
        nuke.oom_context = context
        return engine, tk, sg, context
    except Exception as e:
        raise RuntimeError(f"Toolkit bootstrap failed: {e}")


class SaveDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(SaveDialog, self).__init__(parent)

        self.setWindowTitle("OOM Save Panel")
        self.setMinimumWidth(420)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)

        self.engine, self.tk, self.sg, self.context = _ensure_toolkit()
        self.project = self.context.project
        self.entity = self.context.entity

        # Inputs
        self.step_field = QtWidgets.QComboBox()
        self.task_field = QtWidgets.QComboBox()
        self.task_field.setEnabled(False)

        self.name_field = QtWidgets.QLineEdit()
        self.name_field.setPlaceholderText("name_of_nuke_script")

        layout = QtWidgets.QFormLayout(self)
        layout.addRow("Script Name*", self.name_field)
        layout.addRow("Pipeline Step*", self.step_field)
        layout.addRow("Task*", self.task_field)

        # Populate and wire
        self.populate_pipeline_steps()
        self.step_field.currentIndexChanged.connect(self.populate_tasks)
        self.step_field.currentIndexChanged.connect(self.update_save_enabled)
        self.task_field.currentIndexChanged.connect(self.update_save_enabled)
        self.name_field.textChanged.connect(self.update_save_enabled)

        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        self.save_btn = QtWidgets.QPushButton("Save Script")
        self.cancel_btn = QtWidgets.QPushButton("Close")
        self.save_btn.clicked.connect(self.save_script)
        self.cancel_btn.clicked.connect(self.close)
        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(self.cancel_btn)
        layout.addRow(button_layout)

        self.update_save_enabled()

    def populate_pipeline_steps(self):
        self.step_field.clear()
        self.step_field.addItem("-- Select Step --", None)

        entity_type = self.entity["type"] if self.entity else None
        self.pipeline_steps = (
            self.sg.find("Step", [["entity_type", "is", entity_type]], ["code", "name"])
            if entity_type
            else []
        )
        for step in self.pipeline_steps:
            self.step_field.addItem(step.get("code") or step.get("name"), step)

    def populate_tasks(self):
        step = self.step_field.currentData()
        if not step:
            self.task_field.clear()
            self.task_field.addItem("-- Select Task --", None)
            self.task_field.setEnabled(False)
            return

        filters = [
            ["project", "is", self.project],
            ["entity", "is", self.entity],
            ["step", "is", step],
        ]
        self.tasks = self.sg.find("Task", filters, ["content", "name"])

        self.task_field.clear()
        self.task_field.addItem("-- Select Task --", None)
        for task in self.tasks:
            label = task.get("content") or task.get("name")
            self.task_field.addItem(label, task)

        has_tasks = len(self.tasks) > 0
        self.task_field.setEnabled(has_tasks)

        if not has_tasks:
            QtWidgets.QMessageBox.information(
                self,
                "No Tasks for Step",
                "No Tasks exist in ShotGrid for this Step on this Shot.\n"
                "Please create a Task in ShotGrid and try again.",
            )

        self.update_save_enabled()

    def update_save_enabled(self):
        name_ok = bool(re.match(r"^[a-zA-Z0-9_]+$", self.name_field.text().strip()))
        step_ok = self.step_field.currentData() is not None
        task_ok = (
            self.task_field.isEnabled() and self.task_field.currentData() is not None
        )
        self.save_btn.setEnabled(name_ok and step_ok and task_ok)

    def save_script(self):
        name = self.name_field.text().strip()
        if not re.match(r"^[a-zA-Z0-9_]+$", name):
            QtWidgets.QMessageBox.critical(
                self, "Invalid Name", "Name must be alphanumeric with underscores only."
            )
            return

        selected_step = self.step_field.currentData()
        selected_task = self.task_field.currentData()

        if selected_step and "name" not in selected_step:
            selected_step = dict(selected_step)
            selected_step["name"] = selected_step.get("code")
        if selected_task and "name" not in selected_task:
            selected_task = dict(selected_task)
            selected_task["name"] = selected_task.get("content")

        if not selected_step:
            QtWidgets.QMessageBox.critical(
                self, "Missing Step", "You must select a pipeline step."
            )
            return
        if not selected_task:
            QtWidgets.QMessageBox.critical(
                self, "Missing Task", "You must select a Task for this save."
            )
            return

        from sgtk.context import Context

        # Create new context for save target
        new_context = Context(
            tk=self.tk,
            project=self.project,
            entity=self.entity,
            step=selected_step,
            task=selected_task,
        )

        try:
            # Use facility custom Nuke file template
            template = self.tk.templates.get("oom_nuke_file")
            if not template:
                raise RuntimeError("Missing template: oom_nuke_file")

            fields = new_context.as_template_fields(template)
            fields["name"] = name
            # Explicitly set Step to the pipeline step code used in path
            if self.step_field.currentData():
                step_data = self.step_field.currentData()
                fields["Step"] = step_data.get("code") or step_data.get("name")

            existing = self.tk.paths_from_template(
                template, fields, skip_keys=["version"]
            )
            if existing:
                QtWidgets.QMessageBox.critical(
                    self,
                    "File Exists",
                    "A script with this name already exists. Use Version Up instead.",
                )
                return

            fields["version"] = 1
            path = template.apply_fields(fields)
            # Ensure parent directory exists
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if os.path.exists(path):
                QtWidgets.QMessageBox.critical(
                    self,
                    "File Exists",
                    "A script with this name already exists. Use Version Up instead.",
                )
                return
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Template Error", f"Failed to resolve path:\n{e}"
            )
            return

        # Switch engine/context and save
        try:
            nuke.oom_context = new_context
            if nuke.oom_engine:
                nuke.oom_engine.change_context(new_context)

            # Save the script
            nuke.scriptSaveAs(path)
            print(f"[oom] Saved Nuke script to: {path}")

            # Publish to ShotGrid (match Version Up behavior)
            try:
                # Resolve publish type
                pft = self.sg.find_one(
                    "PublishedFileType", [["code", "is", "oom_nuke_file"]]
                )
                if not pft:
                    raise RuntimeError("Missing PublishedFileType: oom_nuke_file")

                # Ensure entity id exists
                entity = new_context.entity
                if not (entity and entity.get("id")):
                    raise RuntimeError("Entity missing ID")

                # Name and version from template fields
                name = name  # explicit; already validated above
                version = 1

                publish_data = {
                    "project": new_context.project,
                    "entity": {"type": entity["type"], "id": entity["id"]},
                    "task": new_context.task,
                    "path": {"local_path": path},
                    "name": name,
                    "code": name,
                    "version_number": version,
                    "published_file_type": pft,
                }

                published_file = self.sg.create("PublishedFile", publish_data)
                print(f"[oom] Published script to ShotGrid: {published_file}")
                QtWidgets.QMessageBox.information(
                    self, "Saved", f"Saved and published:\n{path}"
                )
            except Exception as pub_err:
                # Save succeeded; warn if publish failed
                QtWidgets.QMessageBox.warning(
                    self,
                    "Publish Warning",
                    f"Saved script, but publish failed:\n{pub_err}",
                )

            self.close()
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, "Save Failed", f"Failed to save script:\n{e}"
            )


def launch():
    global _SAVE_DIALOG_REF
    try:
        dlg = SaveDialog(parent=_main_window())
        _SAVE_DIALOG_REF = dlg
        dlg.show()
        try:
            dlg.raise_()
            dlg.activateWindow()
        except Exception:
            pass
        print("[oom] SaveDialog launched")
    except Exception as e:
        nuke.message(f"[oom] Failed to launch SaveDialog:\n{e}")
