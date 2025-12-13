import hou
from PySide6 import QtWidgets, QtCore
import sgtk
import re
import os

class VersionUpDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(VersionUpDialog, self).__init__(parent)

        self.setWindowTitle("OOM Version Up")
        self.setMinimumWidth(400)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)

        self.tk = hou.session.oom_tk
        self.sg = self.tk.shotgun
        self.context = hou.session.oom_context
        self.project = self.context.project
        self.entity = self.context.entity

        layout = QtWidgets.QVBoxLayout(self)

        self.version_btn = QtWidgets.QPushButton("Version Up and Save")
        self.version_btn.clicked.connect(self.version_up)

        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.close)

        layout.addWidget(self.version_btn)
        layout.addWidget(self.cancel_btn)

    def version_up(self):
        try:
            current_path = hou.hipFile.path()
            if not os.path.exists(current_path):
                QtWidgets.QMessageBox.critical(
                    self,
                    "No HIP File",
                    "No saved HIP file detected. Please save your file first.",
                )
                return

            template = self.tk.templates["oom_hip_file"]
            fields = template.get_fields(current_path)

            # auto-increment version
            all_versions = self.tk.paths_from_template(template, fields, skip_keys=["version"])
            version_numbers = []
            for p in all_versions:
                try:
                    v_fields = template.get_fields(p)
                    version_numbers.append(v_fields.get("version", 0))
                except:
                    pass

            new_version = max(version_numbers) + 1 if version_numbers else 1
            fields["version"] = new_version
            new_path = template.apply_fields(fields)

            hou.hipFile.save(new_path)
            print(f"[oom] Versioned up HIP file to: {new_path}")

            # get name from fields
            name = fields["name"]

            # Task required for publish
            if not self.context.task:
                QtWidgets.QMessageBox.critical(
                    self,
                    "Missing Task",
                    "Version Up requires a Task in context. Open Save and choose a Task.",
                )
                return

            # publish
            try:
                pft = self.sg.find_one("PublishedFileType", [["code", "is", "Houdini Scene"]])
                if not pft:
                    raise RuntimeError("Missing PublishedFileType: Houdini Scene")

                if "id" not in self.entity:
                    raise RuntimeError("Entity missing ID")

                # build base publish data (Task enforced above)
                publish_data = {
                    "project": self.project,
                    "entity": {"type": self.entity["type"], "id": self.entity["id"]},
                    "task": self.context.task,
                    "path": {"local_path": new_path},
                    "name": name,
                    "code": name,
                    "version_number": new_version,
                    "published_file_type": pft
                }

                published_file = self.sg.create("PublishedFile", publish_data)
                print(f"[oom] Published versioned file to ShotGrid: {published_file}")
                QtWidgets.QMessageBox.information(self, "Success", f"Versioned up and published:\n{new_path}")
                self.close()
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Publish Warning", f"Saved HIP file but failed to publish:\n{e}")

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to version up:\n{e}")

def launch():
    hip_path = hou.hipFile.path()
    if not os.path.exists(hip_path):
        QtWidgets.QMessageBox.critical(
            hou.ui.mainQtWindow(),
            "No HIP File",
            "No saved HIP file detected. Please save your file first.",
        )
        return

    dlg = VersionUpDialog()
    dlg.setParent(hou.ui.mainQtWindow(), QtCore.Qt.Window)
    dlg.show()

launch()
