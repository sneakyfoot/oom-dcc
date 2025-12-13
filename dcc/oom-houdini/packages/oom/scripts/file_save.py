import hou
from PySide6 import QtWidgets, QtCore
from sgtk.context import Context
import sgtk
import re
import os

class SaveDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(SaveDialog, self).__init__(parent)

        self.setWindowTitle("OOM Save Panel")
        self.setMinimumWidth(400)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)

        self.tk = hou.session.oom_tk
        self.sg = self.tk.shotgun
        self.context = hou.session.oom_context
        self.project = self.context.project
        self.entity = self.context.entity

        # Inputs
        self.step_field = QtWidgets.QComboBox()
        self.task_field = QtWidgets.QComboBox()
        self.task_field.setEnabled(False)

        self.name_field = QtWidgets.QLineEdit()
        self.name_field.setPlaceholderText("name_of_hip_file")

        layout = QtWidgets.QFormLayout(self)
        layout.addRow("HIP Name*", self.name_field)
        layout.addRow("Pipeline Step*", self.step_field)
        layout.addRow("Task*", self.task_field)

        # Populate initial data and wire events
        self.populate_pipeline_steps()
        self.step_field.currentIndexChanged.connect(self.populate_tasks)
        self.step_field.currentIndexChanged.connect(self.update_save_enabled)
        self.task_field.currentIndexChanged.connect(self.update_save_enabled)
        self.name_field.textChanged.connect(self.update_save_enabled)

        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        self.save_btn = QtWidgets.QPushButton("Save HIP")
        self.cancel_btn = QtWidgets.QPushButton("Close")
        self.save_btn.clicked.connect(self.save_hip_file)
        self.cancel_btn.clicked.connect(self.close)
        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(self.cancel_btn)

        layout.addRow(button_layout)

        # Initial button state
        self.update_save_enabled()

    def populate_pipeline_steps(self):
        self.step_field.clear()
        self.step_field.addItem("-- Select Step --", None)

        # Show all Steps configured for this entity type in SG
        self.pipeline_steps = self.sg.find(
            "Step",
            [["entity_type", "is", self.entity["type"]]],
            ["code", "name"]
        )
        for step in self.pipeline_steps:
            # Ensure the UI label always displays the step code
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
            ["step", "is", step]
        ]
        self.tasks = self.sg.find("Task", filters, ["content", "name"])

        # Clear and repopulate with a placeholder so nothing is auto-selected
        self.task_field.clear()
        self.task_field.addItem("-- Select Task --", None)
        for task in self.tasks:
            label = task.get("content") or task.get("name")
            self.task_field.addItem(label, task)

        # Enable if any tasks available
        has_tasks = len(self.tasks) > 0
        self.task_field.setEnabled(has_tasks)

        # If there are no tasks under this Step, keep Save disabled and inform the user
        if not has_tasks:
            QtWidgets.QMessageBox.information(
                self,
                "No Tasks for Step",
                "No Tasks exist in ShotGrid for this Step on this Shot.\n"
                "Please create a Task in ShotGrid and try again.",
            )

        # Re-evaluate Save button state
        self.update_save_enabled()

    def update_save_enabled(self):
        """Enable Save only when name, step, and task are all valid."""
        name_ok = bool(re.match(r"^[a-zA-Z0-9_]+$", self.name_field.text().strip()))
        step_ok = self.step_field.currentData() is not None
        task_ok = self.task_field.isEnabled() and self.task_field.currentData() is not None
        self.save_btn.setEnabled(name_ok and step_ok and task_ok)


    def save_hip_file(self):
        name = self.name_field.text().strip()
        if not re.match(r"^[a-zA-Z0-9_]+$", name):
            QtWidgets.QMessageBox.critical(self, "Invalid Name", "Name must be alphanumeric with underscores only.")
            return

        selected_step = self.step_field.currentData()
        selected_task = self.task_field.currentData()

        # Ensure name fields exist for proper Context string representation
        if selected_step and "name" not in selected_step:
            selected_step = dict(selected_step)
            selected_step["name"] = selected_step.get("code")
        if selected_task and "name" not in selected_task:
            selected_task = dict(selected_task)
            selected_task["name"] = selected_task.get("content")

        if not selected_step:
            QtWidgets.QMessageBox.critical(self, "Missing Step", "You must select a pipeline step.")
            return
        if not selected_task:
            QtWidgets.QMessageBox.critical(self, "Missing Task", "You must select a Task for this save.")
            return

        # Create a context instance but do not set it yet. We only switch
        # contexts after we verify the file does not already exist.
        new_context = Context(
            tk=self.tk,
            project=self.project,
            entity=self.entity,
            step=selected_step,
            task=selected_task
        )

        # Resolve path
        try:
            template = self.tk.templates["oom_hip_file"]
            fields = new_context.as_template_fields(template)
            fields["name"] = name

            # check for existing versions of this file
            existing = self.tk.paths_from_template(
                template, fields, skip_keys=["version"]
            )
            if existing:
                QtWidgets.QMessageBox.critical(
                    self,
                    "File Exists",
                    "A file with this name already exists. Use Version Up instead.",
                )
                return

            fields["version"] = 1
            version = fields["version"]
            path = template.apply_fields(fields)
            if os.path.exists(path):
                QtWidgets.QMessageBox.critical(
                    self,
                    "File Exists",
                    "A file with this name already exists. Use Version Up instead.",
                )
                return
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Template Error", f"Failed to resolve path:\n{e}")
            return

        # At this point the file doesn't exist so we can safely switch context
        hou.session.oom_context = new_context
        hou.session.oom_engine.change_context(new_context)
        print(
            f"[oom] Context set to step {hou.session.oom_context.step} "
            f"task {hou.session.oom_context.task}"
        )

        # Save the file
        try:
            hou.hipFile.save(path)
            print(f"[oom] Saved HIP file to: {path}")
            print(
                f"[oom] Current context step: {hou.session.oom_context.step}, "
                f"task: {hou.session.oom_context.task}"
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Save Failed", f"Failed to save HIP file:\n{e}")
            return

        # Publish to ShotGrid
        try:
            pft = self.sg.find_one("PublishedFileType", [["code", "is", "Houdini Scene"]])
            if not pft:
                raise RuntimeError("Missing PublishedFileType: Houdini Scene")
            
            # sanitize entity
            entity = self.entity
            if "id" not in entity:
                raise RuntimeError("Entity is missing ID")
            
            # build base publish data (Task is required and set)
            publish_data = {
                "project": self.project,
                "entity": {"type": entity["type"], "id": entity["id"]},
                "task": selected_task,
                "path": {"local_path": path},
                "name": name,
                "code": name,
                "version_number": version,
                "published_file_type": pft
            }

            published_file = self.sg.create("PublishedFile", publish_data)
            print(f"[oom] Published to ShotGrid: {published_file}")
            QtWidgets.QMessageBox.information(self, "Success", f"HIP saved & published:\n{path}")
            self.close()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Publish Warning", f"Saved HIP file but failed to publish:\n{e}")


def launch():
    dlg = SaveDialog()
    dlg.setParent(hou.ui.mainQtWindow(), QtCore.Qt.Window)
    dlg.show()

launch()
