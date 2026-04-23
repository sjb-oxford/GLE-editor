#!/usr/bin/env python3
"""Fast-launch entry point that shows a splash before heavy app imports."""

from __future__ import annotations

import sys
import traceback

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen


def _build_splash_pixmap() -> QPixmap:
    pixmap = QPixmap(520, 220)
    pixmap.fill(QColor("#f4f8ff"))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.fillRect(24, 24, 472, 172, QColor("#d8ebff"))
    painter.setPen(QPen(QColor("#2f6db3"), 2))
    painter.drawRect(24, 24, 472, 172)

    painter.setPen(QColor("#153b66"))
    painter.setFont(QFont("Helvetica", 24, QFont.Weight.Bold))
    painter.drawText(48, 95, "GLE Editor")

    painter.setFont(QFont("Helvetica", 12))
    painter.drawText(48, 132, "Loading interface and preview tools...")
    painter.end()
    return pixmap


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    splash = QSplashScreen(_build_splash_pixmap())
    splash.showMessage(
        "Starting GLE Editor...",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        QColor("#153b66"),
    )
    splash.show()
    app.processEvents()

    try:
        import gle_editor_app

        window = gle_editor_app.GleApp()
    except Exception as exc:
        splash.close()
        QMessageBox.critical(
            None,
            "Startup error",
            f"GLE Editor failed to start:\n{exc}",
        )
        traceback.print_exc()
        return 1

    window.show()
    splash.finish(window)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
