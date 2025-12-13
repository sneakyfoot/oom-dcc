import os

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


_VERSION_DIALOG_REF = None


def _ensure_toolkit():
    engine = getattr(nuke, 'oom_engine', None)
    tk = getattr(nuke, 'oom_tk', None)
    context = getattr(nuke, 'oom_context', None)

    if engine and tk:
        return engine, tk, tk.shotgun, context

    try:
        import oom_sg_tk  # noqa: F401
        from oom_bootstrap import bootstrap
        engine, tk, sg = bootstrap()
        context = getattr(nuke, 'oom_context', None)
        nuke.oom_engine = engine
        nuke.oom_tk = tk
        return engine, tk, sg, context
    except Exception as e:
        raise RuntimeError(f"Toolkit bootstrap failed: {e}")


class VersionUpDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(VersionUpDialog, self).__init__(parent)

        self.setWindowTitle("OOM Version Up")
        self.setMinimumWidth(360)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)

        self.engine, self.tk, self.sg, self.context = _ensure_toolkit()

        layout = QtWidgets.QVBoxLayout(self)
        self.version_btn = QtWidgets.QPushButton("Version Up and Save")
        self.version_btn.clicked.connect(self.version_up)
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.close)
        layout.addWidget(self.version_btn)
        layout.addWidget(self.cancel_btn)

    def version_up(self):
        try:
            current_path = nuke.root().name()
            if not current_path or current_path in (None, 'Root', 'Untitled') or not os.path.isabs(current_path):
                QtWidgets.QMessageBox.critical(
                    self,
                    "No Script File",
                    "No saved Nuke script detected. Please save your script first.",
                )
                return

            template = self.tk.templates.get("oom_nuke_file")
            if not template:
                QtWidgets.QMessageBox.critical(self, "Template Error", "Missing template: oom_nuke_file")
                return

            fields = template.get_fields(current_path)
            all_versions = self.tk.paths_from_template(template, fields, skip_keys=["version"])

            version_numbers = []
            for p in all_versions:
                try:
                    v_fields = template.get_fields(p)
                    version_numbers.append(v_fields.get("version", 0))
                except Exception:
                    pass

            new_version = max(version_numbers) + 1 if version_numbers else 1
            fields["version"] = new_version
            new_path = template.apply_fields(fields)

            nuke.scriptSaveAs(new_path)
            print(f"[oom] Versioned up Nuke script to: {new_path}")

            # Require a Task for publish
            if not (self.context and self.context.task):
                QtWidgets.QMessageBox.critical(
                    self,
                    "Missing Task",
                    "Version Up requires a Task in context. Open Save and choose a Task.",
                )
                return

            try:
                pft = self.sg.find_one("PublishedFileType", [["code", "is", "oom_nuke_file"]])
                if not pft:
                    raise RuntimeError("Missing PublishedFileType: oom_nuke_file")

                entity = self.context.entity
                if not (entity and entity.get("id")):
                    raise RuntimeError("Entity missing ID")

                name = fields.get("name")
                publish_data = {
                    "project": self.context.project,
                    "entity": {"type": entity["type"], "id": entity["id"]},
                    "task": self.context.task,
                    "path": {"local_path": new_path},
                    "name": name,
                    "code": name,
                    "version_number": new_version,
                    "published_file_type": pft,
                }

                published_file = self.sg.create("PublishedFile", publish_data)
                print(f"[oom] Published versioned script to ShotGrid: {published_file}")
                QtWidgets.QMessageBox.information(self, "Success", f"Versioned up and published:\n{new_path}")
                self.close()
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Publish Warning", f"Saved script but failed to publish:\n{e}")

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to version up:\n{e}")


def launch():
    global _VERSION_DIALOG_REF
    try:
        dlg = VersionUpDialog(parent=_main_window())
        _VERSION_DIALOG_REF = dlg
        dlg.show()
        try:
            dlg.raise_(); dlg.activateWindow()
        except Exception:
            pass
        print('[oom] VersionUpDialog launched')
    except Exception as e:
        nuke.message(f"[oom] Failed to launch VersionUpDialog:\n{e}")
