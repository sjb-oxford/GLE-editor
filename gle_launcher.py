#!/usr/bin/env python3
"""Fast-launch entry point that shows a splash before heavy app imports."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen


def _resource_search_dirs() -> list[Path]:
    dirs: list[Path] = []

    if hasattr(sys, "_MEIPASS"):
        dirs.append(Path(getattr(sys, "_MEIPASS")))

    script_dir = Path(__file__).resolve().parent
    exe_dir = Path(sys.executable).resolve().parent

    dirs.extend(
        [
            script_dir,
            exe_dir,
            exe_dir.parent,
            exe_dir.parent / "Resources",
            Path.cwd(),
        ]
    )

    unique: list[Path] = []
    seen: set[str] = set()
    for d in dirs:
        key = str(d)
        if key not in seen:
            unique.append(d)
            seen.add(key)
    return unique


def _load_icon_pixmap(size: int) -> QPixmap:
    relative_candidates = [
        Path("icon.iconset/icon_512x512.png"),
        Path("icon.iconset/icon_256x256.png"),
        Path("icon.iconset/icon_128x128.png"),
        Path("icon.iconset/icon_64x64.png"),
        Path("icon.png"),
        Path("gle-icon-large.png"),
        Path("icon.icns"),
    ]
    for base in _resource_search_dirs():
        for rel in relative_candidates:
            path = base / rel
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
