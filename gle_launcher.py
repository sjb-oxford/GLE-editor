#!/usr/bin/env python3
"""Fast-launch entry point that shows a splash before heavy app imports."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen


def _resource_base_dir() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent


def _load_icon_pixmap(size: int) -> QPixmap:
    base = _resource_base_dir()
    candidates = [
        base / "icon.iconset" / "icon_512x512.png",
        base / "icon.iconset" / "icon_256x256.png",
        base / "icon.iconset" / "icon_128x128.png",
    ]
    for path in candidates:
        if path.exists():
            pix = QPixmap(str(path))
            if not pix.isNull():
                return pix.scaled(
                    size,
                    size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
    return QPixmap()


def _build_splash_pixmap() -> QPixmap:
    pixmap = QPixmap(520, 220)
    pixmap.fill(QColor("#f4f8ff"))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.fillRect(24, 24, 472, 172, QColor("#d8ebff"))
    painter.setPen(QPen(QColor("#2f6db3"), 2))
    painter.drawRect(24, 24, 472, 172)

    icon = _load_icon_pixmap(124)
    if not icon.isNull():
        painter.drawPixmap(36, 48, icon)

    painter.setPen(QColor("#153b66"))
    painter.setFont(QFont("Helvetica", 24, QFont.Weight.Bold))
    painter.drawText(190, 95, "GLE Editor")

    painter.setFont(QFont("Helvetica", 12))
    painter.drawText(190, 132, "Loading interface and preview tools...")
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
