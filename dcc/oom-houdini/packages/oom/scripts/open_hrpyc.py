import os

from PySide6 import QtCore, QtWidgets
import hou
import hrpyc


class HrpcServerDialog(QtWidgets.QDialog):
    """Floating window to manage the Houdini RPC server."""

    def __init__(self, parent=None):
        super(HrpcServerDialog, self).__init__(parent)
        port = int(os.environ.get("OOM_HRPYC_PORT", "18811"))
        self.setWindowTitle(f"Houdini RPC Server  (port {port})")
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)

        layout = QtWidgets.QVBoxLayout(self)
        self.close_btn = QtWidgets.QPushButton("Close Server")
        self.close_btn.clicked.connect(self.close_server)
        layout.addWidget(self.close_btn)

        # Start the RPC server on the configured port
        self.server = hrpyc.start_server(port=port)

    def close_server(self):
        try:
            self.server.close()
        except Exception:
            pass
        self.close()


def launch():
    dlg = HrpcServerDialog()
    dlg.setParent(hou.ui.mainQtWindow(), QtCore.Qt.Window)
    dlg.show()


launch()
