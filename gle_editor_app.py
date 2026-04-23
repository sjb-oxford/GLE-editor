#!/usr/bin/env python3
"""
GLE Editor with integrated PDF preview.

Requirements:
    pip install pyside6 pymupdf

System requirement:
    gle (Graphics Layout Engine) must be on the system PATH.

Run:
    python gle-editor.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QRectF, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplashScreen,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

APP_ORG = "GLE-Editor"
APP_NAME = "GleEditorApp"
ABOUT_TEXT = (
    "GLE Editor\n"
    "Stephen Blundell\n"
    "University of Oxford\n"
    "Department of Physics\n"
    "Version 1.0\n"
    "April 2026"
)

COMMON_BIN_DIRS = ["/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin"]


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
        base / "icon.iconset" / "icon_32x32.png",
        base / "icon.png",
        base / "gle-icon-large.png",
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


def _load_app_icon() -> QIcon:
    pix = _load_icon_pixmap(128)
    if pix.isNull():
        return QIcon()
    return QIcon(pix)


def _build_splash_pixmap() -> QPixmap:
    pixmap = QPixmap(520, 220)
    pixmap.fill(QColor("#f4f8ff"))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.fillRect(24, 24, 472, 172, QColor("#d8ebff"))
    painter.setPen(QPen(QColor("#2f6db3"), 2))
    painter.drawRect(24, 24, 472, 172)

    icon = _load_icon_pixmap(72)
    if not icon.isNull():
        painter.drawPixmap(52, 58, icon)

    painter.setPen(QColor("#153b66"))
    title_font = QFont("Helvetica", 24, QFont.Weight.Bold)
    painter.setFont(title_font)
    painter.drawText(140, 95, "GLE Editor")

    subtitle_font = QFont("Helvetica", 12)
    painter.setFont(subtitle_font)
    painter.drawText(140, 132, "Loading interface and preview tools...")

    painter.end()
    return pixmap


class AboutPopup(QWidget):
    def __init__(self, parent: QWidget | None = None, app=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About")
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setStyleSheet(
            "QWidget { background-color: white; border: 1px solid #888; }"
            "QLabel { border: none; }"
            "QPushButton { border: 1px solid #888; padding: 6px 12px; border-radius: 3px; }"
        )
        self._app = app

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)

        about_icon = QLabel()
        about_pix = _load_icon_pixmap(72)
        if not about_pix.isNull():
            about_icon.setPixmap(about_pix)
        about_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_icon.setFixedHeight(78)
        layout.addWidget(about_icon)

        label = QLabel(ABOUT_TEXT)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setFont(QFont("Helvetica", 11))
        layout.addWidget(label)

        # GLE configuration button
        btn_config = QPushButton("Configure GLE path...")
        btn_config.clicked.connect(self._configure_gle)
        layout.addWidget(btn_config)

        # Display current GLE path if available
        if app and app._gle_executable:
            info_label = QLabel(f"GLE path: {app._gle_executable}")
            info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            info_label.setFont(QFont("Helvetica", 9))
            info_label.setStyleSheet("color: #666;")
            layout.addWidget(info_label)

    def _configure_gle(self) -> None:
        if self._app:
            user_path = self._app._prompt_for_gle_path()
            if user_path:
                self._app._gle_executable = user_path
                self._app.settings.setValue("gle_executable", user_path)
                self._app.settings.sync()
                QMessageBox.information(
                    self,
                    "GLE path saved",
                    f"GLE executable path saved:\n{user_path}",
                )
                self.close()
                self._app.show_about()  # Refresh the dialog
            else:
                QMessageBox.information(self, "Cancelled", "GLE path configuration cancelled.")

    def mousePressEvent(self, event) -> None:
        # Only close on click if clicking on the text area, not buttons
        if isinstance(event.widget(), QLabel):
            self.close()
        super().mousePressEvent(event)

# ─────────────────────────────────────────────────────────────────────────────
# Snippets – add new (label, text) tuples here to extend "Insert common".
# Use "\n" for newlines within snippet text.
# ─────────────────────────────────────────────────────────────────────────────
COMMON_SNIPPETS: list[tuple[str, str]] = [
    ("standard style", r'''size 20 20
begin texpreamble
    \usepackage{amsmath}
    \usepackage{amssymb}
end texpreamble
set lwidth 0.04
set font texcmr
set texscale scale
set arrowsize 0.6
set hei 0.8
set just center'''),
    ("Function plot", r'''size 20 20
begin texpreamble
    \usepackage{amsmath}
    \usepackage{amssymb}
end texpreamble

set lwidth 0.04
set font texcmr
set texscale scale
set arrowsize 0.6
set hei 0.8
set just center

amove 3 3
begin graph
 size 16 16
 fullsize
 let d1 = x*x from 0 to 10
 d1 line
 xtitle "\tex{$x$\,(m)}" dist 0.5
 ytitle "\tex{$y$\, (MHz)" dist 0.5
 xaxis min 0 max 10 hei 0.6
 yaxis min 0 max 100 hei 0.6
! xplaces 0 5 10 15 20
! yplaces 0 5 10 15 20
 x2ticks off
 y2ticks off
 ysubticks off
 xticks length 0.3
 yticks length 0.3
end graph'''),
    ("Data plot", r'''size 20 20
begin texpreamble
    \usepackage{amsmath}
    \usepackage{amssymb}
end texpreamble

set lwidth 0.04
set font texcmr
set texscale scale
set arrowsize 0.6
set hei 0.8
set just center

amove 3 3
begin graph
 size 12 12
 fullsize
 data dyb2c2-zf.dat d1=c4,c9 d2=c4,c10
 d1 marker fcircle err d2
 xtitle "\tex{$T$\,(K)}" dist 0.5
 ytitle "\tex{$\nu$\, (MHz)" dist 0.5
 xaxis min 0 max 300 hei 0.6
 yaxis min 0 max 100 hei 0.6
! xplaces 0 5 10 15 20
! yplaces 0 5 10 15 20
 x2ticks off
 y2ticks off
 ysubticks off
 xticks length 0.3
 yticks length 0.3
end graph'''),
    ("Raw data plot", r'''size 20 20
begin texpreamble
    \usepackage{amsmath}
    \usepackage{amssymb}
end texpreamble

set lwidth 0.04
set font texcmr
set texscale scale
set arrowsize 0.6
set hei 0.8
set just center

amove 3 3
begin graph
 size 12 12
 fullsize
 data 4096-zf.dat 
 d1 marker fcircle err d2
 xtitle "\tex{$T$\,(K)}" dist 0.5
 ytitle "\tex{$\nu$\, (MHz)" dist 0.5
 xaxis min 0 max 20 hei 0.6
 yaxis min 0 max 20 hei 0.6
 xplaces 0 5 10 15 20
 yplaces 0 5 10 15 20
 x2ticks off
 y2ticks off
 ysubticks off
 xticks length 0.3
 yticks length 0.3
end graph'''),
    ("Simple graph", r'''size 10 10
set lwidth 0.04
set font texcmr
set hei 1
set just center

amove 1 1
rline 8 0 arrow end
rmove 0.3 -0.2
text {\it x}

amove 1 1
rline 0 8 arrow end
rmove 0.0 0.3
text {\it E}'''),
]


# ─────────────────────────────────────────────────────────────────────────────
# PDF viewer widget
# ─────────────────────────────────────────────────────────────────────────────

class PdfViewer(QGraphicsView):
    amove_pressed = Signal(float, float)  # x, y in cm from bottom-left
    aline_pressed = Signal(float, float, float, float)  # x1, y1, x2, y2 in cm from bottom-left
    box_pressed = Signal(float, float, float, float)  # x1, y1, x2, y2 in cm from bottom-left
    box_fill_pressed = Signal(float, float, float, float)  # x1, y1, x2, y2 in cm from bottom-left
    circle_pressed = Signal(float, float, float, float)  # x1, y1, x2, y2 in cm from bottom-left
    circle_fill_pressed = Signal(float, float, float, float)  # x1, y1, x2, y2 in cm from bottom-left
    ellipse_pressed = Signal(float, float, float, float)  # x1, y1, x2, y2 in cm from bottom-left
    ellipse_fill_pressed = Signal(float, float, float, float)  # x1, y1, x2, y2 in cm from bottom-left
    text_pressed = Signal(float, float)  # x, y in cm from bottom-left
    arrow_end_pressed = Signal(float, float, float, float)  # x1, y1, x2, y2 in cm from bottom-left
    arrow_start_pressed = Signal(float, float, float, float)  # x1, y1, x2, y2 in cm from bottom-left
    arrow_both_pressed = Signal(float, float, float, float)  # x1, y1, x2, y2 in cm from bottom-left

    def __init__(self) -> None:
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setStyleSheet(
            "QGraphicsView {"
            " background-color: #d8ebff;"
            " border: 2px solid #2f6db3;"
            "}"
        )
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
            | QPainter.RenderHint.TextAntialiasing
        )
        self._zoom = 1.5
        self._grid_visible = False
        self._grid_items: list = []
        self._click_marker_items: list = []
        self._drag_marker_items: list = []
        self._drag_tracking_second = False
        self._drag_second_active = False
        self._drag_start_px: tuple[float, float] | None = None
        self._pixmap_size: tuple[int, int] = (0, 0)
        self._amove_mode = False
        self._aline_mode = False
        self._aline_point1: tuple[float, float] | None = None
        self._box_mode = False
        self._box_point1: tuple[float, float] | None = None
        self._box_fill_mode = False
        self._box_fill_point1: tuple[float, float] | None = None
        self._circle_mode = False
        self._circle_point1: tuple[float, float] | None = None
        self._circle_fill_mode = False
        self._circle_fill_point1: tuple[float, float] | None = None
        self._ellipse_mode = False
        self._ellipse_point1: tuple[float, float] | None = None
        self._ellipse_fill_mode = False
        self._ellipse_fill_point1: tuple[float, float] | None = None
        self._text_mode = False
        self._arrow_end_mode = False
        self._arrow_start_mode = False
        self._arrow_both_mode = False
        self._arrow_point1: tuple[float, float] | None = None

    def load_pdf(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            import fitz  # PyMuPDF

            with fitz.open(str(path)) as doc:
                if doc.page_count < 1:
                    return
                page = doc.load_page(0)
                pix = page.get_pixmap(
                    matrix=fitz.Matrix(self._zoom, self._zoom), alpha=False
                )
                image = QImage(
                    pix.samples, pix.width, pix.height, pix.stride,
                    QImage.Format.Format_RGB888,
                ).copy()
                pixmap = QPixmap.fromImage(image)

            # scene.clear() deletes all items, including previous grid lines
            self._scene.clear()
            self._grid_items.clear()
            self._click_marker_items.clear()
            self._drag_marker_items.clear()
            self._scene.addPixmap(pixmap)
            self._scene.setSceneRect(QRectF(pixmap.rect()))
            self._pixmap_size = (pixmap.width(), pixmap.height())
            if self._grid_visible:
                self._draw_grid()
            self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        except Exception as e:
            print(f"PDF viewer error: {e}")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._scene.sceneRect().isEmpty():
            self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def mousePressEvent(self, event) -> None:
        if (
            self._amove_mode
            or self._aline_mode
            or self._box_mode
            or self._box_fill_mode
            or self._circle_mode
            or self._circle_fill_mode
            or self._ellipse_mode
            or self._ellipse_fill_mode
            or self._text_mode
            or self._arrow_end_mode
            or self._arrow_start_mode
            or self._arrow_both_mode
        ):
            # Convert view coordinates to scene coordinates
            scene_pos = self.mapToScene(event.pos())
            x_px, y_px = scene_pos.x(), scene_pos.y()
            w, h = self._pixmap_size
            # Convert to cm from bottom-left (GLE origin)
            # 1 cm = 28.3465 PDF points × zoom = pixels
            step_px = 28.3465 * self._zoom
            x_cm = x_px / step_px
            y_cm = (h - y_px) / step_px
            
            if self._amove_mode:
                self._draw_click_marker(x_px, y_px, QColor(220, 30, 30))  # red first/only click
                self.amove_pressed.emit(x_cm, y_cm)
            elif self._aline_mode:
                if self._aline_point1 is None:
                    # First click: store the point
                    self._draw_click_marker(x_px, y_px, QColor(220, 30, 30))  # red first click
                    self._aline_point1 = (x_cm, y_cm)
                    self._start_second_drag_tracking(x_px, y_px)
                else:
                    # Second click: emit both points
                    self._draw_click_marker(x_px, y_px, QColor(20, 160, 20))  # green second click
                    x1, y1 = self._aline_point1
                    self._aline_point1 = None  # Reset for next aline sequence
                    self._emit_after_second_marker(
                        lambda x1=x1, y1=y1, x2=x_cm, y2=y_cm: self.aline_pressed.emit(x1, y1, x2, y2)
                    )
            elif self._box_mode:
                if self._box_point1 is None:
                    # First click: store the point
                    self._draw_click_marker(x_px, y_px, QColor(220, 30, 30))  # red first click
                    self._box_point1 = (x_cm, y_cm)
                    self._start_second_drag_tracking(x_px, y_px)
                else:
                    # Second click: emit both points
                    self._draw_click_marker(x_px, y_px, QColor(20, 160, 20))  # green second click
                    x1, y1 = self._box_point1
                    self._box_point1 = None  # Reset for next box sequence
                    self._emit_after_second_marker(
                        lambda x1=x1, y1=y1, x2=x_cm, y2=y_cm: self.box_pressed.emit(x1, y1, x2, y2)
                    )
            elif self._box_fill_mode:
                if self._box_fill_point1 is None:
                    # First click: store the point
                    self._draw_click_marker(x_px, y_px, QColor(220, 30, 30))  # red first click
                    self._box_fill_point1 = (x_cm, y_cm)
                    self._start_second_drag_tracking(x_px, y_px)
                else:
                    # Second click: emit both points
                    self._draw_click_marker(x_px, y_px, QColor(20, 160, 20))  # green second click
                    x1, y1 = self._box_fill_point1
                    self._box_fill_point1 = None  # Reset for next box fill sequence
                    self._emit_after_second_marker(
                        lambda x1=x1, y1=y1, x2=x_cm, y2=y_cm: self.box_fill_pressed.emit(x1, y1, x2, y2)
                    )
            elif self._circle_mode:
                if self._circle_point1 is None:
                    self._draw_click_marker(x_px, y_px, QColor(220, 30, 30))
                    self._circle_point1 = (x_cm, y_cm)
                    self._start_second_drag_tracking(x_px, y_px)
                else:
                    self._draw_click_marker(x_px, y_px, QColor(20, 160, 20))
                    x1, y1 = self._circle_point1
                    self._circle_point1 = None
                    self._emit_after_second_marker(
                        lambda x1=x1, y1=y1, x2=x_cm, y2=y_cm: self.circle_pressed.emit(x1, y1, x2, y2)
                    )
            elif self._circle_fill_mode:
                if self._circle_fill_point1 is None:
                    self._draw_click_marker(x_px, y_px, QColor(220, 30, 30))
                    self._circle_fill_point1 = (x_cm, y_cm)
                    self._start_second_drag_tracking(x_px, y_px)
                else:
                    self._draw_click_marker(x_px, y_px, QColor(20, 160, 20))
                    x1, y1 = self._circle_fill_point1
                    self._circle_fill_point1 = None
                    self._emit_after_second_marker(
                        lambda x1=x1, y1=y1, x2=x_cm, y2=y_cm: self.circle_fill_pressed.emit(x1, y1, x2, y2)
                    )
            elif self._ellipse_mode:
                if self._ellipse_point1 is None:
                    self._draw_click_marker(x_px, y_px, QColor(220, 30, 30))
                    self._ellipse_point1 = (x_cm, y_cm)
                    self._start_second_drag_tracking(x_px, y_px)
                else:
                    self._draw_click_marker(x_px, y_px, QColor(20, 160, 20))
                    x1, y1 = self._ellipse_point1
                    self._ellipse_point1 = None
                    self._emit_after_second_marker(
                        lambda x1=x1, y1=y1, x2=x_cm, y2=y_cm: self.ellipse_pressed.emit(x1, y1, x2, y2)
                    )
            elif self._ellipse_fill_mode:
                if self._ellipse_fill_point1 is None:
                    self._draw_click_marker(x_px, y_px, QColor(220, 30, 30))
                    self._ellipse_fill_point1 = (x_cm, y_cm)
                    self._start_second_drag_tracking(x_px, y_px)
                else:
                    self._draw_click_marker(x_px, y_px, QColor(20, 160, 20))
                    x1, y1 = self._ellipse_fill_point1
                    self._ellipse_fill_point1 = None
                    self._emit_after_second_marker(
                        lambda x1=x1, y1=y1, x2=x_cm, y2=y_cm: self.ellipse_fill_pressed.emit(x1, y1, x2, y2)
                    )
            elif self._text_mode:
                self._draw_click_marker(x_px, y_px, QColor(220, 30, 30))  # red first/only click
                self.text_pressed.emit(x_cm, y_cm)
            elif self._arrow_end_mode or self._arrow_start_mode or self._arrow_both_mode:
                if self._arrow_point1 is None:
                    # First click: store the point
                    self._draw_click_marker(x_px, y_px, QColor(220, 30, 30))  # red first click
                    self._arrow_point1 = (x_cm, y_cm)
                    self._start_second_drag_tracking(x_px, y_px)
                else:
                    # Second click: emit both points
                    self._draw_click_marker(x_px, y_px, QColor(20, 160, 20))  # green second click
                    x1, y1 = self._arrow_point1
                    self._arrow_point1 = None  # Reset for next arrow sequence
                    if self._arrow_end_mode:
                        self._emit_after_second_marker(
                            lambda x1=x1, y1=y1, x2=x_cm, y2=y_cm: self.arrow_end_pressed.emit(x1, y1, x2, y2)
                        )
                    elif self._arrow_start_mode:
                        self._emit_after_second_marker(
                            lambda x1=x1, y1=y1, x2=x_cm, y2=y_cm: self.arrow_start_pressed.emit(x1, y1, x2, y2)
                        )
                    else:
                        self._emit_after_second_marker(
                            lambda x1=x1, y1=y1, x2=x_cm, y2=y_cm: self.arrow_both_pressed.emit(x1, y1, x2, y2)
                        )
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_tracking_second and (event.buttons() & Qt.MouseButton.LeftButton):
            scene_pos = self.mapToScene(event.pos())
            x_px, y_px = scene_pos.x(), scene_pos.y()

            if self._drag_start_px is not None and not self._drag_second_active:
                dx = x_px - self._drag_start_px[0]
                dy = y_px - self._drag_start_px[1]
                if (dx * dx + dy * dy) >= (4.0 * 4.0):
                    self._drag_second_active = True

            if self._drag_second_active:
                self._draw_drag_marker(x_px, y_px, QColor(20, 160, 20))
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        consumed = False
        if self._drag_tracking_second and event.button() == Qt.MouseButton.LeftButton:
            if self._drag_second_active:
                scene_pos = self.mapToScene(event.pos())
                x_px, y_px = scene_pos.x(), scene_pos.y()
                w, h = self._pixmap_size
                step_px = 28.3465 * self._zoom
                x_cm = x_px / step_px
                y_cm = (h - y_px) / step_px

                self._clear_drag_marker()
                self._draw_click_marker(x_px, y_px, QColor(20, 160, 20))  # green second click

                if self._aline_mode and self._aline_point1 is not None:
                    x1, y1 = self._aline_point1
                    self._aline_point1 = None
                    self._emit_after_second_marker(
                        lambda x1=x1, y1=y1, x2=x_cm, y2=y_cm: self.aline_pressed.emit(x1, y1, x2, y2)
                    )
                    consumed = True
                elif self._box_mode and self._box_point1 is not None:
                    x1, y1 = self._box_point1
                    self._box_point1 = None
                    self._emit_after_second_marker(
                        lambda x1=x1, y1=y1, x2=x_cm, y2=y_cm: self.box_pressed.emit(x1, y1, x2, y2)
                    )
                    consumed = True
                elif self._box_fill_mode and self._box_fill_point1 is not None:
                    x1, y1 = self._box_fill_point1
                    self._box_fill_point1 = None
                    self._emit_after_second_marker(
                        lambda x1=x1, y1=y1, x2=x_cm, y2=y_cm: self.box_fill_pressed.emit(x1, y1, x2, y2)
                    )
                    consumed = True
                elif self._circle_mode and self._circle_point1 is not None:
                    x1, y1 = self._circle_point1
                    self._circle_point1 = None
                    self._emit_after_second_marker(
                        lambda x1=x1, y1=y1, x2=x_cm, y2=y_cm: self.circle_pressed.emit(x1, y1, x2, y2)
                    )
                    consumed = True
                elif self._circle_fill_mode and self._circle_fill_point1 is not None:
                    x1, y1 = self._circle_fill_point1
                    self._circle_fill_point1 = None
                    self._emit_after_second_marker(
                        lambda x1=x1, y1=y1, x2=x_cm, y2=y_cm: self.circle_fill_pressed.emit(x1, y1, x2, y2)
                    )
                    consumed = True
                elif self._ellipse_mode and self._ellipse_point1 is not None:
                    x1, y1 = self._ellipse_point1
                    self._ellipse_point1 = None
                    self._emit_after_second_marker(
                        lambda x1=x1, y1=y1, x2=x_cm, y2=y_cm: self.ellipse_pressed.emit(x1, y1, x2, y2)
                    )
                    consumed = True
                elif self._ellipse_fill_mode and self._ellipse_fill_point1 is not None:
                    x1, y1 = self._ellipse_fill_point1
                    self._ellipse_fill_point1 = None
                    self._emit_after_second_marker(
                        lambda x1=x1, y1=y1, x2=x_cm, y2=y_cm: self.ellipse_fill_pressed.emit(x1, y1, x2, y2)
                    )
                    consumed = True
                elif (self._arrow_end_mode or self._arrow_start_mode or self._arrow_both_mode) and self._arrow_point1 is not None:
                    x1, y1 = self._arrow_point1
                    self._arrow_point1 = None
                    if self._arrow_end_mode:
                        self._emit_after_second_marker(
                            lambda x1=x1, y1=y1, x2=x_cm, y2=y_cm: self.arrow_end_pressed.emit(x1, y1, x2, y2)
                        )
                    elif self._arrow_start_mode:
                        self._emit_after_second_marker(
                            lambda x1=x1, y1=y1, x2=x_cm, y2=y_cm: self.arrow_start_pressed.emit(x1, y1, x2, y2)
                        )
                    else:
                        self._emit_after_second_marker(
                            lambda x1=x1, y1=y1, x2=x_cm, y2=y_cm: self.arrow_both_pressed.emit(x1, y1, x2, y2)
                        )
                    consumed = True

            self._stop_second_drag_tracking()

        if not consumed:
            super().mouseReleaseEvent(event)

    def set_amove(self, enabled: bool) -> None:
        self._amove_mode = enabled
        if enabled:
            # Disable multi-point modes when enabling amove
            self._aline_mode = False
            self._aline_point1 = None
            self._box_mode = False
            self._box_point1 = None
            self._box_fill_mode = False
            self._box_fill_point1 = None
            self._circle_mode = False
            self._circle_point1 = None
            self._circle_fill_mode = False
            self._circle_fill_point1 = None
            self._ellipse_mode = False
            self._ellipse_point1 = None
            self._ellipse_fill_mode = False
            self._ellipse_fill_point1 = None
            self._text_mode = False
            self._arrow_end_mode = False
            self._arrow_start_mode = False
            self._arrow_both_mode = False
            self._arrow_point1 = None
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_aline(self, enabled: bool) -> None:
        self._aline_mode = enabled
        if enabled:
            # Disable other modes when enabling aline
            self._amove_mode = False
            self._aline_point1 = None
            self._box_mode = False
            self._box_point1 = None
            self._box_fill_mode = False
            self._box_fill_point1 = None
            self._circle_mode = False
            self._circle_point1 = None
            self._circle_fill_mode = False
            self._circle_fill_point1 = None
            self._ellipse_mode = False
            self._ellipse_point1 = None
            self._ellipse_fill_mode = False
            self._ellipse_fill_point1 = None
            self._text_mode = False
            self._arrow_end_mode = False
            self._arrow_start_mode = False
            self._arrow_both_mode = False
            self._arrow_point1 = None
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self._aline_point1 = None
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_box(self, enabled: bool) -> None:
        self._box_mode = enabled
        if enabled:
            # Disable other modes when enabling box
            self._amove_mode = False
            self._aline_mode = False
            self._aline_point1 = None
            self._box_fill_mode = False
            self._box_fill_point1 = None
            self._circle_mode = False
            self._circle_point1 = None
            self._circle_fill_mode = False
            self._circle_fill_point1 = None
            self._ellipse_mode = False
            self._ellipse_point1 = None
            self._ellipse_fill_mode = False
            self._ellipse_fill_point1 = None
            self._text_mode = False
            self._arrow_end_mode = False
            self._arrow_start_mode = False
            self._arrow_both_mode = False
            self._arrow_point1 = None
            self._box_point1 = None
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self._box_point1 = None
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_box_fill(self, enabled: bool) -> None:
        self._box_fill_mode = enabled
        if enabled:
            # Disable other modes when enabling box fill
            self._amove_mode = False
            self._aline_mode = False
            self._aline_point1 = None
            self._box_mode = False
            self._box_point1 = None
            self._circle_mode = False
            self._circle_point1 = None
            self._circle_fill_mode = False
            self._circle_fill_point1 = None
            self._ellipse_mode = False
            self._ellipse_point1 = None
            self._ellipse_fill_mode = False
            self._ellipse_fill_point1 = None
            self._text_mode = False
            self._arrow_end_mode = False
            self._arrow_start_mode = False
            self._arrow_both_mode = False
            self._arrow_point1 = None
            self._box_fill_point1 = None
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self._box_fill_point1 = None
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_circle(self, enabled: bool) -> None:
        self._circle_mode = enabled
        if enabled:
            self._amove_mode = False
            self._aline_mode = False
            self._aline_point1 = None
            self._box_mode = False
            self._box_point1 = None
            self._box_fill_mode = False
            self._box_fill_point1 = None
            self._circle_fill_mode = False
            self._circle_fill_point1 = None
            self._ellipse_mode = False
            self._ellipse_point1 = None
            self._ellipse_fill_mode = False
            self._ellipse_fill_point1 = None
            self._text_mode = False
            self._arrow_end_mode = False
            self._arrow_start_mode = False
            self._arrow_both_mode = False
            self._arrow_point1 = None
            self._circle_point1 = None
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self._circle_point1 = None
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_circle_fill(self, enabled: bool) -> None:
        self._circle_fill_mode = enabled
        if enabled:
            self._amove_mode = False
            self._aline_mode = False
            self._aline_point1 = None
            self._box_mode = False
            self._box_point1 = None
            self._box_fill_mode = False
            self._box_fill_point1 = None
            self._circle_mode = False
            self._circle_point1 = None
            self._ellipse_mode = False
            self._ellipse_point1 = None
            self._ellipse_fill_mode = False
            self._ellipse_fill_point1 = None
            self._text_mode = False
            self._arrow_end_mode = False
            self._arrow_start_mode = False
            self._arrow_both_mode = False
            self._arrow_point1 = None
            self._circle_fill_point1 = None
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self._circle_fill_point1 = None
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_ellipse(self, enabled: bool) -> None:
        self._ellipse_mode = enabled
        if enabled:
            self._amove_mode = False
            self._aline_mode = False
            self._aline_point1 = None
            self._box_mode = False
            self._box_point1 = None
            self._box_fill_mode = False
            self._box_fill_point1 = None
            self._circle_mode = False
            self._circle_point1 = None
            self._circle_fill_mode = False
            self._circle_fill_point1 = None
            self._text_mode = False
            self._arrow_end_mode = False
            self._arrow_start_mode = False
            self._arrow_both_mode = False
            self._arrow_point1 = None
            self._ellipse_point1 = None
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self._ellipse_point1 = None
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_ellipse_fill(self, enabled: bool) -> None:
        self._ellipse_fill_mode = enabled
        if enabled:
            self._amove_mode = False
            self._aline_mode = False
            self._aline_point1 = None
            self._box_mode = False
            self._box_point1 = None
            self._box_fill_mode = False
            self._box_fill_point1 = None
            self._circle_mode = False
            self._circle_point1 = None
            self._circle_fill_mode = False
            self._circle_fill_point1 = None
            self._ellipse_mode = False
            self._ellipse_point1 = None
            self._text_mode = False
            self._arrow_end_mode = False
            self._arrow_start_mode = False
            self._arrow_both_mode = False
            self._arrow_point1 = None
            self._ellipse_fill_point1 = None
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self._ellipse_fill_point1 = None
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_arrow_end(self, enabled: bool) -> None:
        self._arrow_end_mode = enabled
        if enabled:
            # Disable other modes when enabling right-arrow line
            self._amove_mode = False
            self._aline_mode = False
            self._aline_point1 = None
            self._box_mode = False
            self._box_point1 = None
            self._box_fill_mode = False
            self._box_fill_point1 = None
            self._circle_mode = False
            self._circle_point1 = None
            self._circle_fill_mode = False
            self._circle_fill_point1 = None
            self._ellipse_mode = False
            self._ellipse_point1 = None
            self._ellipse_fill_mode = False
            self._ellipse_fill_point1 = None
            self._text_mode = False
            self._arrow_start_mode = False
            self._arrow_both_mode = False
            self._arrow_point1 = None
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self._arrow_point1 = None
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_arrow_start(self, enabled: bool) -> None:
        self._arrow_start_mode = enabled
        if enabled:
            # Disable other modes when enabling left-arrow line
            self._amove_mode = False
            self._aline_mode = False
            self._aline_point1 = None
            self._box_mode = False
            self._box_point1 = None
            self._box_fill_mode = False
            self._box_fill_point1 = None
            self._circle_mode = False
            self._circle_point1 = None
            self._circle_fill_mode = False
            self._circle_fill_point1 = None
            self._ellipse_mode = False
            self._ellipse_point1 = None
            self._ellipse_fill_mode = False
            self._ellipse_fill_point1 = None
            self._text_mode = False
            self._arrow_end_mode = False
            self._arrow_both_mode = False
            self._arrow_point1 = None
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self._arrow_point1 = None
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_arrow_both(self, enabled: bool) -> None:
        self._arrow_both_mode = enabled
        if enabled:
            # Disable other modes when enabling two-arrow line
            self._amove_mode = False
            self._aline_mode = False
            self._aline_point1 = None
            self._box_mode = False
            self._box_point1 = None
            self._box_fill_mode = False
            self._box_fill_point1 = None
            self._circle_mode = False
            self._circle_point1 = None
            self._ellipse_mode = False
            self._ellipse_point1 = None
            self._text_mode = False
            self._arrow_end_mode = False
            self._arrow_start_mode = False
            self._arrow_point1 = None
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self._arrow_point1 = None
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_text(self, enabled: bool) -> None:
        self._text_mode = enabled
        if enabled:
            # Disable other modes when enabling text
            self._amove_mode = False
            self._aline_mode = False
            self._aline_point1 = None
            self._box_mode = False
            self._box_point1 = None
            self._box_fill_mode = False
            self._box_fill_point1 = None
            self._circle_mode = False
            self._circle_point1 = None
            self._circle_fill_mode = False
            self._circle_fill_point1 = None
            self._ellipse_mode = False
            self._ellipse_point1 = None
            self._ellipse_fill_mode = False
            self._ellipse_fill_point1 = None
            self._arrow_end_mode = False
            self._arrow_start_mode = False
            self._arrow_both_mode = False
            self._arrow_point1 = None
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_grid(self, visible: bool) -> None:
        self._grid_visible = visible
        if visible:
            self._draw_grid()
        else:
            self._clear_grid()

    def _clear_grid(self) -> None:
        for item in self._grid_items:
            try:
                self._scene.removeItem(item)
            except RuntimeError:
                # Item may already be deleted by scene.clear()
                pass
        self._grid_items.clear()

    def _draw_click_marker(self, x_px: float, y_px: float, color: QColor) -> None:
        w, h = self._pixmap_size
        if w == 0 or h == 0:
            return

        # Keep markers on the rendered PDF area.
        x = max(0.0, min(float(w), x_px))
        y = max(0.0, min(float(h), y_px))

        pen = QPen(color)
        pen.setCosmetic(True)
        pen.setWidth(2)

        v = self._scene.addLine(x, 0, x, h, pen)
        hline = self._scene.addLine(0, y, w, y, pen)
        v.setZValue(20)
        hline.setZValue(20)
        self._click_marker_items.extend([v, hline])

    def _draw_drag_marker(self, x_px: float, y_px: float, color: QColor) -> None:
        self._clear_drag_marker()
        w, h = self._pixmap_size
        if w == 0 or h == 0:
            return

        x = max(0.0, min(float(w), x_px))
        y = max(0.0, min(float(h), y_px))

        pen = QPen(color)
        pen.setCosmetic(True)
        pen.setWidth(2)

        v = self._scene.addLine(x, 0, x, h, pen)
        hline = self._scene.addLine(0, y, w, y, pen)
        v.setZValue(21)
        hline.setZValue(21)
        self._drag_marker_items.extend([v, hline])

    def _clear_drag_marker(self) -> None:
        for item in self._drag_marker_items:
            try:
                self._scene.removeItem(item)
            except RuntimeError:
                pass
        self._drag_marker_items.clear()

    def _start_second_drag_tracking(self, x_px: float, y_px: float) -> None:
        self._drag_tracking_second = True
        self._drag_second_active = False
        self._drag_start_px = (x_px, y_px)

    def _stop_second_drag_tracking(self) -> None:
        self._drag_tracking_second = False
        self._drag_second_active = False
        self._drag_start_px = None
        self._clear_drag_marker()

    def _emit_after_second_marker(self, callback) -> None:
        # Force a repaint, then delay action so the green marker is visible.
        self.viewport().update()
        QApplication.processEvents()
        QTimer.singleShot(500, callback)

    def _draw_grid(self) -> None:
        self._clear_grid()
        w, h = self._pixmap_size
        if w == 0 or h == 0:
            return
        # 1 cm = 28.3465 PDF points; each point is rendered as self._zoom pixels
        step = 28.3465 * self._zoom
        pen = QPen(QColor(30, 80, 200, 90))   # semi-transparent blue
        pen.setCosmetic(True)                  # 1 px wide regardless of zoom
        pen.setWidth(1)
        x = step
        while x < w:
            item = self._scene.addLine(x, 0, x, h, pen)
            item.setZValue(10)
            self._grid_items.append(item)
            x += step
        y = step
        while y < h:
            item = self._scene.addLine(0, y, w, y, pen)
            item.setZValue(10)
            self._grid_items.append(item)
            y += step


# ─────────────────────────────────────────────────────────────────────────────
# Main application window
# ─────────────────────────────────────────────────────────────────────────────

class GleApp(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("GLE Editor")
        app_icon = _load_app_icon()
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)
        self.resize(1400, 860)

        self.settings = QSettings(APP_ORG, APP_NAME)
        self._current_path: Path | None = None
        self._autosave_dirty = False
        self._gle_executable: str | None = None

        # Autosave 1 second after the last keystroke
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(1000)
        self._autosave_timer.timeout.connect(self._autosave)

        self._build_ui()
        self._initialize_gle_path()
        self._restore_state()
        self.editor.moveCursor(QTextCursor.MoveOperation.End)
        self.editor.setFocus()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # Top control bar — all buttons share uniform size/style via bar_widget stylesheet
        bar_widget = QWidget()
        bar = QHBoxLayout(bar_widget)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(4)
        # Shared style applied to every QPushButton and QToolButton child
        bar_widget.setStyleSheet(
            "QPushButton, QToolButton {"
            "  border: 1px solid #888;"
            "  border-radius: 3px;"
            "  padding: 4px 10px;"
            "  font-size: 13px;"
            "  min-height: 22px;"
            "}"
            "QPushButton:pressed, QToolButton:pressed { border-color: #444; }"
            "QToolButton::menu-indicator { image: none; }"
        )

        icon_label = QLabel()
        header_icon = _load_icon_pixmap(32)
        if not header_icon.isNull():
            icon_label.setPixmap(header_icon)
        icon_label.setFixedSize(34, 34)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bar.addWidget(icon_label)

        btn_new = QPushButton("New")
        btn_new.clicked.connect(self.new_file)
        btn_new.setStyleSheet("background-color: #ffb6c1;")  # pink
        bar.addWidget(btn_new)

        btn_load = QPushButton("Load")
        btn_load.clicked.connect(self.load_file)
        btn_load.setStyleSheet("background-color: #add8e6;")  # light blue
        bar.addWidget(btn_load)

        btn_save = QPushButton("Save")
        btn_save.clicked.connect(self.save_file)
        btn_save.setStyleSheet("background-color: #c8a882;")  # light brown
        bar.addWidget(btn_save)

        btn_saveas = QPushButton("Save As")
        btn_saveas.clicked.connect(self.save_file_as)
        btn_saveas.setStyleSheet("background-color: #a0724a; color: white;")  # brown
        bar.addWidget(btn_saveas)

        btn_undo = QPushButton("Undo")
        btn_undo.clicked.connect(self.undo_edit)
        btn_undo.setStyleSheet("background-color: #ffff99;")  # yellow
        bar.addWidget(btn_undo)

        btn_find = QPushButton("Find / Replace")
        btn_find.clicked.connect(self.toggle_find_bar)
        btn_find.setStyleSheet("background-color: #ffb347;")  # orange
        bar.addWidget(btn_find)

        btn_gle = QPushButton("GLE")
        btn_gle.clicked.connect(self.run_gle)
        btn_gle.setStyleSheet("background-color: #228b22; color: white;")  # green
        bar.addWidget(btn_gle)

        btn_eps = QPushButton("EPS")
        btn_eps.clicked.connect(self.run_eps)
        btn_eps.setStyleSheet("background-color: #90ee90;")  # light green
        bar.addWidget(btn_eps)

        btn_grid = QPushButton("Grid")
        btn_grid.setCheckable(True)
        btn_grid.setStyleSheet(
            "QPushButton { background-color: #d8b4fe; }"
            "QPushButton:checked { background-color: #7c3aed; color: white; }"
        )
        bar.addWidget(btn_grid)

        btn_add_element = QPushButton("Add element")
        btn_add_element.clicked.connect(self.toggle_element_bar)
        btn_add_element.setStyleSheet("background-color: #4169e1; color: white;")  # blue
        bar.addWidget(btn_add_element)

        self.insert_menu_button = QToolButton()
        self.insert_menu_button.setText("Insert common")
        self.insert_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.insert_menu_button.setMenu(self._build_insert_menu())
        self.insert_menu_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.insert_menu_button.setStyleSheet("background-color: #ff80ff;")  # light magenta
        bar.addWidget(self.insert_menu_button)

        btn_about = QPushButton("About")
        btn_about.clicked.connect(self.show_about)
        btn_about.setStyleSheet("background-color: white;")
        bar.addWidget(btn_about)

        btn_quit = QPushButton("Quit")
        btn_quit.clicked.connect(self.quit_app)
        btn_quit.setStyleSheet("background-color: #cc0000; color: white;")  # red
        bar.addWidget(btn_quit)

        bar.addStretch(1)

        self.status_label = QLabel("")
        bar.addWidget(self.status_label)

        root.addWidget(bar_widget)

        # ── Add element bar (hidden until toggled) ─────────────────────────────
        self.element_bar = QWidget()
        self.element_bar.setStyleSheet(
            "QPushButton, QToolButton {"
            "  border: 1px solid #888;"
            "  border-radius: 3px;"
            "  padding: 4px 10px;"
            "  font-size: 13px;"
            "  min-height: 22px;"
            "}"
            "QPushButton:pressed, QToolButton:pressed { border-color: #444; }"
        )
        eb = QHBoxLayout(self.element_bar)
        eb.setContentsMargins(4, 2, 4, 2)
        eb.setSpacing(6)

        self.btn_amove = QPushButton("amove")
        self.btn_amove.setCheckable(True)
        self.btn_amove.setStyleSheet(
            "QPushButton { background-color: #d8c8f0; }"
            "QPushButton:checked { background-color: #9d7db8; color: white; }"
        )
        eb.addWidget(self.btn_amove)

        self.btn_aline = QPushButton("─")
        self.btn_aline.setCheckable(True)
        self.btn_aline.setStyleSheet(
            "QPushButton { background-color: #ede6f7; }"
            "QPushButton:checked { background-color: #b8a8ce; color: white; }"
        )
        eb.addWidget(self.btn_aline)

        self.btn_arrow_end = QPushButton("→")
        self.btn_arrow_end.setCheckable(True)
        self.btn_arrow_end.setStyleSheet(
            "QPushButton { background-color: #fce6e6; }"
            "QPushButton:checked { background-color: #d97070; color: white; }"
        )
        eb.addWidget(self.btn_arrow_end)

        self.btn_arrow_start = QPushButton("←")
        self.btn_arrow_start.setCheckable(True)
        self.btn_arrow_start.setStyleSheet(
            "QPushButton { background-color: #fdeeee; }"
            "QPushButton:checked { background-color: #cf7e7e; color: white; }"
        )
        eb.addWidget(self.btn_arrow_start)

        self.btn_arrow_both = QPushButton("↔")
        self.btn_arrow_both.setCheckable(True)
        self.btn_arrow_both.setStyleSheet(
            "QPushButton { background-color: #fff2e6; }"
            "QPushButton:checked { background-color: #d48f5f; color: white; }"
        )
        eb.addWidget(self.btn_arrow_both)

        self.btn_box = QPushButton("box")
        self.btn_box.setCheckable(True)
        self.btn_box.setStyleSheet(
            "QPushButton { background-color: #f5f1fb; }"
            "QPushButton:checked { background-color: #cbbfe0; color: white; }"
        )
        eb.addWidget(self.btn_box)

        self.btn_box_fill = QPushButton("box fill")
        self.btn_box_fill.setCheckable(True)
        self.btn_box_fill.setStyleSheet(
            "QPushButton { background-color: #e6f2ff; }"
            "QPushButton:checked { background-color: #5b8dc9; color: white; }"
        )
        eb.addWidget(self.btn_box_fill)

        self.btn_circle = QPushButton("circle")
        self.btn_circle.setCheckable(True)
        self.btn_circle.setStyleSheet(
            "QPushButton { background-color: #f3ecff; }"
            "QPushButton:checked { background-color: #9a7fd1; color: white; }"
        )
        eb.addWidget(self.btn_circle)

        self.btn_circle_fill = QPushButton("circle fill")
        self.btn_circle_fill.setCheckable(True)
        self.btn_circle_fill.setStyleSheet(
            "QPushButton { background-color: #ede2ff; }"
            "QPushButton:checked { background-color: #8568c4; color: white; }"
        )
        eb.addWidget(self.btn_circle_fill)

        self.btn_ellipse = QPushButton("ellipse")
        self.btn_ellipse.setCheckable(True)
        self.btn_ellipse.setStyleSheet(
            "QPushButton { background-color: #eef5ff; }"
            "QPushButton:checked { background-color: #6d93c9; color: white; }"
        )
        eb.addWidget(self.btn_ellipse)

        self.btn_ellipse_fill = QPushButton("ellipse fill")
        self.btn_ellipse_fill.setCheckable(True)
        self.btn_ellipse_fill.setStyleSheet(
            "QPushButton { background-color: #e2efff; }"
            "QPushButton:checked { background-color: #4f7ebd; color: white; }"
        )
        eb.addWidget(self.btn_ellipse_fill)

        self.btn_text = QPushButton("text")
        self.btn_text.setCheckable(True)
        self.btn_text.setStyleSheet(
            "QPushButton { background-color: #e8f7e8; }"
            "QPushButton:checked { background-color: #5aa55a; color: white; }"
        )
        eb.addWidget(self.btn_text)

        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Enter text")
        self.text_input.setFixedWidth(220)
        self.text_input.setVisible(False)
        eb.addWidget(self.text_input)

        self.btn_tex = QPushButton("TeX")
        self.btn_tex.setCheckable(True)
        self.btn_tex.setStyleSheet(
            "QPushButton { background-color: #fff8cc; }"
            "QPushButton:checked { background-color: #d4b106; color: white; }"
        )
        self.btn_tex.setVisible(False)
        eb.addWidget(self.btn_tex)

        eb.addStretch(1)
        self.element_bar.setVisible(False)
        root.addWidget(self.element_bar)

        # ── Find / Replace bar (hidden until toggled) ────────────────────────
        self.find_bar = QWidget()
        fb = QHBoxLayout(self.find_bar)
        fb.setContentsMargins(4, 2, 4, 2)
        fb.setSpacing(6)

        fb.addWidget(QLabel("Find:"))
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("search text")
        self.find_edit.setFixedWidth(200)
        self.find_edit.returnPressed.connect(self.find_next)
        fb.addWidget(self.find_edit)

        fb.addWidget(QLabel("Replace:"))
        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText("replacement")
        self.replace_edit.setFixedWidth(200)
        fb.addWidget(self.replace_edit)

        btn_fn = QPushButton("Find Next")
        btn_fn.clicked.connect(self.find_next)
        fb.addWidget(btn_fn)

        btn_fp = QPushButton("Find Prev")
        btn_fp.clicked.connect(self.find_prev)
        fb.addWidget(btn_fp)

        btn_rep = QPushButton("Replace")
        btn_rep.clicked.connect(self.replace_one)
        fb.addWidget(btn_rep)

        btn_repa = QPushButton("Replace All")
        btn_repa.clicked.connect(self.replace_all)
        fb.addWidget(btn_repa)

        self.case_check = QCheckBox("Case sensitive")
        fb.addWidget(self.case_check)

        btn_close_find = QPushButton("✕")
        btn_close_find.setFixedWidth(28)
        btn_close_find.clicked.connect(self.hide_find_bar)
        fb.addWidget(btn_close_find)

        fb.addStretch(1)
        self.find_bar.setVisible(False)
        root.addWidget(self.find_bar)

        # Keyboard shortcuts
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self.show_find_bar)
        QShortcut(QKeySequence("Escape"), self.find_bar).activated.connect(self.hide_find_bar)

        # Left (editor) / right (PDF viewer) panels
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.editor = QPlainTextEdit()
        self.editor.setFont(QFont("Courier New", 11))
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.textChanged.connect(self._on_text_changed)
        splitter.addWidget(self.editor)

        self.pdf_viewer = PdfViewer()
        splitter.addWidget(self.pdf_viewer)

        btn_grid.toggled.connect(self.pdf_viewer.set_grid)
        self.btn_amove.toggled.connect(self.pdf_viewer.set_amove)
        self.pdf_viewer.amove_pressed.connect(self.insert_amove)
        self.btn_aline.toggled.connect(self.pdf_viewer.set_aline)
        self.pdf_viewer.aline_pressed.connect(self.insert_aline)
        self.btn_arrow_end.toggled.connect(self.pdf_viewer.set_arrow_end)
        self.pdf_viewer.arrow_end_pressed.connect(self.insert_arrow_end)
        self.btn_arrow_start.toggled.connect(self.pdf_viewer.set_arrow_start)
        self.pdf_viewer.arrow_start_pressed.connect(self.insert_arrow_start)
        self.btn_arrow_both.toggled.connect(self.pdf_viewer.set_arrow_both)
        self.pdf_viewer.arrow_both_pressed.connect(self.insert_arrow_both)
        self.btn_box.toggled.connect(self.pdf_viewer.set_box)
        self.pdf_viewer.box_pressed.connect(self.insert_box)
        self.btn_circle.toggled.connect(self.pdf_viewer.set_circle)
        self.pdf_viewer.circle_pressed.connect(self.insert_circle)
        self.btn_circle_fill.toggled.connect(self.pdf_viewer.set_circle_fill)
        self.pdf_viewer.circle_fill_pressed.connect(self.insert_circle_fill)
        self.btn_ellipse.toggled.connect(self.pdf_viewer.set_ellipse)
        self.pdf_viewer.ellipse_pressed.connect(self.insert_ellipse)
        self.btn_ellipse_fill.toggled.connect(self.pdf_viewer.set_ellipse_fill)
        self.pdf_viewer.ellipse_fill_pressed.connect(self.insert_ellipse_fill)
        self.btn_box_fill.toggled.connect(self.pdf_viewer.set_box_fill)
        self.pdf_viewer.box_fill_pressed.connect(self.insert_box_fill)
        self.btn_text.toggled.connect(self.pdf_viewer.set_text)
        self.btn_text.toggled.connect(self._toggle_text_entry)
        self.pdf_viewer.text_pressed.connect(self.insert_text_element)

        splitter.setSizes([580, 720])
        root.addWidget(splitter, 1)

    # ── GLE executable initialization ──────────────────────────────────────────

    def _find_gle_executable(self) -> str | None:
        """Try to find the GLE executable using 'which' or check common paths."""
        # Try 'which gle'
        try:
            result = subprocess.run(
                ["which", "gle"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Try shutil.which
        gle_path = shutil.which("gle")
        if gle_path:
            return gle_path

        # GUI apps on macOS often launch with a minimal PATH; probe common install locations.
        for bin_dir in COMMON_BIN_DIRS:
            candidate = Path(bin_dir) / "gle"
            if candidate.exists() and candidate.is_file():
                return str(candidate)

        return None

    def _prompt_for_gle_path(self) -> str | None:
        """Prompt the user to locate the GLE executable."""
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Locate GLE executable",
            "/usr/local/bin",
            "GLE executable (gle);;All files (*.*)",
        )
        if path_str:
            return path_str
        return None

    def _initialize_gle_path(self) -> None:
        """Initialize the GLE executable path on startup."""
        # Check if we have a stored path from previous runs
        stored_path = self.settings.value("gle_executable", "", type=str)
        if stored_path and Path(stored_path).exists():
            self._gle_executable = stored_path
            return

        # Try to find GLE automatically
        found_path = self._find_gle_executable()
        if found_path:
            self._gle_executable = found_path
            self.settings.setValue("gle_executable", found_path)
            self.settings.sync()
            return

        # GLE not found: prompt user to locate it
        QMessageBox.information(
            self,
            "GLE executable not found",
            "The GLE (Graphics Layout Engine) executable was not found on your system.\n\n"
            "Please locate the 'gle' executable in the next dialog.",
        )

        user_path = self._prompt_for_gle_path()
        if user_path:
            self._gle_executable = user_path
            self.settings.setValue("gle_executable", user_path)
            self.settings.sync()
            QMessageBox.information(
                self,
                "GLE path saved",
                f"GLE executable path saved:\n{user_path}",
            )
        else:
            QMessageBox.warning(
                self,
                "GLE not configured",
                "GLE executable was not configured. The GLE and EPS buttons will not work.",
            )

    # ── Persistence ───────────────────────────────────────────────────────────────

    def _restore_state(self) -> None:
        geometry = self.settings.value("window_geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

        last = self.settings.value("last_file", "", type=str)
        if last:
            p = Path(last)
            if p.exists():
                self._load_path(p)
                self.run_gle()

    def _save_state(self) -> None:
        self.settings.setValue("window_geometry", self.saveGeometry())
        if self._current_path:
            self.settings.setValue("last_file", str(self._current_path))
        self.settings.sync()

    def closeEvent(self, event) -> None:
        self._autosave()       # flush any pending change
        self._save_state()
        super().closeEvent(event)

    # ── File operations ───────────────────────────────────────────────────────

    def _start_dir(self) -> str:
        if self._current_path:
            return str(self._current_path.parent)
        saved = self.settings.value("last_dir", "", type=str)
        return saved if saved else str(Path.cwd())

    def _new_dir(self) -> str:
        saved = self.settings.value("last_new_dir", "", type=str)
        return saved if saved else self._start_dir()

    def _saveas_dir(self) -> str:
        if self._current_path:
            return str(self._current_path.parent)
        saved = self.settings.value("last_saveas_dir", "", type=str)
        return saved if saved else self._start_dir()

    def new_file(self) -> None:
        path_str, _ = QFileDialog.getSaveFileName(
            self, "New GLE file", self._new_dir(),
            "GLE files (*.gle)",
        )
        if not path_str:
            return
        if not path_str.endswith(".gle"):
            path_str += ".gle"
        new_path = Path(path_str)
        self.settings.setValue("last_new_dir", str(new_path.parent))

        # Clear editor and assign path; write empty file immediately
        self._autosave_timer.stop()
        self._current_path = new_path
        self.editor.blockSignals(True)
        self.editor.setPlainText("")
        self.editor.blockSignals(False)
        self._autosave_dirty = False
        self._write_current()
        self.pdf_viewer._scene.clear()
        self.setWindowTitle(f"GLE Editor \u2013 {new_path.name}")
        self.status_label.setText(f"New file: {new_path.name}")

    def load_file(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Open GLE file", self._start_dir(),
            "GLE files (*.gle);;All files (*.*)",
        )
        if path_str:
            self._load_path(Path(path_str))

    def _load_path(self, path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as e:
            QMessageBox.critical(self, "Load error", str(e))
            return

        self._current_path = path
        self.settings.setValue("last_dir", str(path.parent))

        # Populate editor without triggering autosave
        self._autosave_timer.stop()
        self.editor.blockSignals(True)
        self.editor.setPlainText(text)
        self.editor.blockSignals(False)
        self._autosave_dirty = False

        self.setWindowTitle(f"GLE Editor – {path.name}")
        self.status_label.setText(f"Loaded {path.name}")

        # Show matching PDF if it already exists
        pdf = path.with_suffix(".pdf")
        if pdf.exists():
            self.pdf_viewer.load_pdf(pdf)

    def save_file(self) -> None:
        if self._current_path is None:
            path_str, _ = QFileDialog.getSaveFileName(
                self, "Save GLE file", self._start_dir(),
                "GLE files (*.gle)",
            )
            if not path_str:
                return
            if not path_str.endswith(".gle"):
                path_str += ".gle"
            self._current_path = Path(path_str)
            self.settings.setValue("last_dir", str(self._current_path.parent))
            self.setWindowTitle(f"GLE Editor – {self._current_path.name}")
        self._write_current()
    def save_file_as(self) -> None:
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Save As", self._saveas_dir(),
            "GLE files (*.gle)",
        )
        if not path_str:
            return
        if not path_str.endswith(".gle"):
            path_str += ".gle"
        self._current_path = Path(path_str)
        self.settings.setValue("last_saveas_dir", str(self._current_path.parent))
        self.setWindowTitle(f"GLE Editor \u2013 {self._current_path.name}")
        self._write_current()
    def _write_current(self) -> None:
        if self._current_path is None:
            return
        try:
            self._current_path.write_text(self.editor.toPlainText(), encoding="utf-8")
            self._autosave_dirty = False
            self.status_label.setText(f"Saved {self._current_path.name}")
        except Exception as e:
            QMessageBox.critical(self, "Save error", str(e))

    def _on_text_changed(self) -> None:
        self._autosave_dirty = True
        if self._current_path is not None:
            self._autosave_timer.start()   # resets the 1-second window

    def _autosave(self) -> None:
        if self._autosave_dirty and self._current_path is not None:
            self._write_current()

    def _reset_element_buttons(self) -> None:
        for btn in (
            self.btn_amove,
            self.btn_aline,
            self.btn_arrow_end,
            self.btn_arrow_start,
            self.btn_arrow_both,
            self.btn_box,
            self.btn_circle,
            self.btn_circle_fill,
            self.btn_ellipse,
            self.btn_ellipse_fill,
            self.btn_box_fill,
            self.btn_text,
        ):
            btn.setChecked(False)

    # ── GLE runner ────────────────────────────────────────────────────────────

    def run_gle(self) -> None:
        if self._current_path is None:
            QMessageBox.warning(self, "No file",
                                "Please load or save a GLE file first.")
            return

        if self._gle_executable is None:
            QMessageBox.critical(
                self, "GLE not configured",
                "GLE executable was not found. Please configure the GLE path in the About dialog.",
            )
            self.status_label.setText("GLE not configured")
            return

        self._write_current()   # make sure the file on disk is current

        self.status_label.setText("Running GLE…")
        QApplication.processEvents()

        env = os.environ.copy()
        path_entries = []
        if self._gle_executable:
            path_entries.append(str(Path(self._gle_executable).parent))
        path_entries.extend(COMMON_BIN_DIRS)
        current_path = env.get("PATH", "")
        if current_path:
            path_entries.append(current_path)
        env["PATH"] = ":".join(dict.fromkeys(path_entries))

        try:
            result = subprocess.run(
                [self._gle_executable, "-device", "pdf", str(self._current_path)],
                capture_output=True,
                text=True,
                cwd=str(self._current_path.parent),
                env=env,
            )
        except (FileNotFoundError, OSError) as e:
            QMessageBox.critical(
                self, "GLE execution failed",
                f"Error running GLE: {str(e)}\n\nThe configured path may be invalid.",
            )
            self.status_label.setText("GLE execution failed")
            return

        if result.returncode != 0:
            msg = (result.stderr.strip() or result.stdout.strip()
                   or "Unknown error")
            QMessageBox.warning(self, "GLE error", msg)
            self.status_label.setText("GLE failed")
            return

        pdf = self._current_path.with_suffix(".pdf")
        if pdf.exists():
            self.pdf_viewer.load_pdf(pdf)
            self.status_label.setText(f"PDF updated: {pdf.name}")
            self._reset_element_buttons()
        else:
            detail = (result.stderr.strip() or result.stdout.strip() or "No diagnostic output from GLE.")
            QMessageBox.warning(
                self,
                "No PDF produced",
                "GLE exited successfully but no PDF file was found next to the .gle file.\n\n"
                f"Checked: {pdf}\n\n"
                f"GLE output:\n{detail}",
            )
            self.status_label.setText("GLE ran but no PDF produced")

    def run_eps(self) -> None:
        if self._current_path is None:
            QMessageBox.warning(self, "No file",
                                "Please load or save a GLE file first.")
            return

        if self._gle_executable is None:
            QMessageBox.critical(
                self, "GLE not configured",
                "GLE executable was not found. Please configure the GLE path in the About dialog.",
            )
            self.status_label.setText("GLE not configured")
            return

        self._write_current()   # make sure the file on disk is current

        self.status_label.setText("Running GLE (EPS)...")
        QApplication.processEvents()

        try:
            result = subprocess.run(
                [self._gle_executable, str(self._current_path)],
                capture_output=True,
                text=True,
                cwd=str(self._current_path.parent),
            )
        except (FileNotFoundError, OSError) as e:
            QMessageBox.critical(
                self, "GLE execution failed",
                f"Error running GLE: {str(e)}\n\nThe configured path may be invalid.",
            )
            self.status_label.setText("GLE execution failed")
            return

        if result.returncode != 0:
            msg = (result.stderr.strip() or result.stdout.strip()
                   or "Unknown error")
            QMessageBox.warning(self, "GLE error", msg)
            self.status_label.setText("EPS failed")
            return

        eps = self._current_path.with_suffix(".eps")
        if eps.exists():
            self.status_label.setText(f"EPS updated: {eps.name}")
        else:
            self.status_label.setText("GLE ran but no EPS produced")

    def quit_app(self) -> None:
        self.close()

    def show_about(self) -> None:
        self._about_popup = AboutPopup(self, app=self)
        self._about_popup.adjustSize()
        center = self.geometry().center()
        self._about_popup.move(
            center.x() - self._about_popup.width() // 2,
            center.y() - self._about_popup.height() // 2,
        )
        self._about_popup.show()
        self._about_popup.raise_()
        self._about_popup.activateWindow()

    def undo_edit(self) -> None:
        self.editor.undo()

    def insert_amove(self, x: float, y: float) -> None:
        # Insert "amove x y" on its own line
        text = f"\namove {x:.2f} {y:.2f}\n"
        cursor = self.editor.textCursor()
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def insert_aline(self, x1: float, y1: float, x2: float, y2: float) -> None:
        # Insert amove and aline on their own lines
        text = f"\namove {x1:.2f} {y1:.2f}\naline {x2:.2f} {y2:.2f}\n"
        cursor = self.editor.textCursor()
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        self.run_gle()

    def insert_box(self, x1: float, y1: float, x2: float, y2: float) -> None:
        # Insert amove and box on their own lines
        dx = x2 - x1
        dy = y2 - y1
        text = f"\namove {x1:.2f} {y1:.2f}\nbox {dx:.2f} {dy:.2f}\n"
        cursor = self.editor.textCursor()
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        self.run_gle()

    def insert_circle(self, x1: float, y1: float, x2: float, y2: float) -> None:
        radius = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        text = f"\namove {x1:.2f} {y1:.2f}\ncircle {radius:.2f}\n"
        cursor = self.editor.textCursor()
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        self.run_gle()

    def insert_circle_fill(self, x1: float, y1: float, x2: float, y2: float) -> None:
        radius = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        text = f"\namove {x1:.2f} {y1:.2f}\ncircle {radius:.2f} fill grey20\n"
        cursor = self.editor.textCursor()
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        self.run_gle()

    def insert_ellipse(self, x1: float, y1: float, x2: float, y2: float) -> None:
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        text = f"\namove {x1:.2f} {y1:.2f}\nellipse {dx:.2f} {dy:.2f}\n"
        cursor = self.editor.textCursor()
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        self.run_gle()

    def insert_ellipse_fill(self, x1: float, y1: float, x2: float, y2: float) -> None:
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        text = f"\namove {x1:.2f} {y1:.2f}\nellipse {dx:.2f} {dy:.2f} fill grey20\n"
        cursor = self.editor.textCursor()
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        self.run_gle()

    def insert_box_fill(self, x1: float, y1: float, x2: float, y2: float) -> None:
        # Insert amove and box with fill option on their own lines
        dx = x2 - x1
        dy = y2 - y1
        text = f"\namove {x1:.2f} {y1:.2f}\nbox {dx:.2f} {dy:.2f} fill grey20\n"
        cursor = self.editor.textCursor()
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        self.run_gle()

    def insert_text_element(self, x: float, y: float) -> None:
        entered_text = self.text_input.text()
        if self.btn_tex.isChecked():
            line = f"text \\tex{{{entered_text}}}"
        else:
            line = f"text {entered_text}"
        text = f"\namove {x:.2f} {y:.2f}\n{line}\n"
        cursor = self.editor.textCursor()
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        self.run_gle()
        self.btn_text.setChecked(False)

    def insert_arrow_end(self, x1: float, y1: float, x2: float, y2: float) -> None:
        # Insert exactly like aline, with "arrow end" suffix
        text = f"\namove {x1:.2f} {y1:.2f}\naline {x2:.2f} {y2:.2f} arrow end\n"
        cursor = self.editor.textCursor()
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        self.run_gle()

    def insert_arrow_start(self, x1: float, y1: float, x2: float, y2: float) -> None:
        # Insert exactly like aline, with "arrow start" suffix
        text = f"\namove {x1:.2f} {y1:.2f}\naline {x2:.2f} {y2:.2f} arrow start\n"
        cursor = self.editor.textCursor()
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        self.run_gle()

    def insert_arrow_both(self, x1: float, y1: float, x2: float, y2: float) -> None:
        # Insert exactly like aline, with "arrow both" suffix
        text = f"\namove {x1:.2f} {y1:.2f}\naline {x2:.2f} {y2:.2f} arrow both\n"
        cursor = self.editor.textCursor()
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        self.run_gle()

    # ── Find / Replace ────────────────────────────────────────────────────────

    def _toggle_text_entry(self, enabled: bool) -> None:
        self.text_input.setVisible(enabled)
        self.btn_tex.setVisible(enabled)
        if enabled:
            self.text_input.setFocus()
            self.text_input.selectAll()
        else:
            self.btn_tex.setChecked(False)
            self.text_input.clear()

    def toggle_find_bar(self) -> None:
        if self.find_bar.isVisible():
            self.hide_find_bar()
        else:
            self.show_find_bar()

    def toggle_element_bar(self) -> None:
        if self.element_bar.isVisible():
            self.element_bar.setVisible(False)
        else:
            self.element_bar.setVisible(True)

    def show_find_bar(self) -> None:
        self.find_bar.setVisible(True)
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def hide_find_bar(self) -> None:
        self.find_bar.setVisible(False)
        self.editor.setFocus()

    def _find_flags(self):
        from PySide6.QtGui import QTextDocument
        flags = QTextDocument.FindFlag(0)
        if self.case_check.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        return flags

    def find_next(self) -> None:
        term = self.find_edit.text()
        if not term:
            return
        found = self.editor.find(term, self._find_flags())
        if not found:
            # Wrap around from top
            cursor = self.editor.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            self.editor.setTextCursor(cursor)
            found = self.editor.find(term, self._find_flags())
            if not found:
                self.status_label.setText(f"'{term}' not found")

    def find_prev(self) -> None:
        from PySide6.QtGui import QTextDocument
        term = self.find_edit.text()
        if not term:
            return
        flags = self._find_flags() | QTextDocument.FindFlag.FindBackward
        found = self.editor.find(term, flags)
        if not found:
            # Wrap around from bottom
            cursor = self.editor.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self.editor.setTextCursor(cursor)
            found = self.editor.find(term, flags)
            if not found:
                self.status_label.setText(f"'{term}' not found")

    def replace_one(self) -> None:
        term = self.find_edit.text()
        replacement = self.replace_edit.text()
        if not term:
            return
        cursor = self.editor.textCursor()
        # If there's a matching selection already, replace it
        if cursor.hasSelection() and cursor.selectedText() == (term if self.case_check.isChecked() else cursor.selectedText()):
            cmp_sel = cursor.selectedText()
            cmp_term = term if self.case_check.isChecked() else term
            if (self.case_check.isChecked() and cmp_sel == cmp_term) or \
               (not self.case_check.isChecked() and cmp_sel.lower() == cmp_term.lower()):
                cursor.insertText(replacement)
                self.editor.setTextCursor(cursor)
        # Advance to next match
        self.find_next()

    def replace_all(self) -> None:
        term = self.find_edit.text()
        replacement = self.replace_edit.text()
        if not term:
            return
        # Work on the raw text to count and replace all
        text = self.editor.toPlainText()
        if self.case_check.isChecked():
            count = text.count(term)
            new_text = text.replace(term, replacement)
        else:
            import re
            count = len(re.findall(re.escape(term), text, flags=re.IGNORECASE))
            new_text = re.sub(re.escape(term), replacement, text, flags=re.IGNORECASE)
        if count == 0:
            self.status_label.setText(f"'{term}' not found")
            return
        # Replace via cursor so the undo stack captures it as one operation
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()
        cursor.select(cursor.SelectionType.Document)
        cursor.insertText(new_text)
        cursor.endEditBlock()
        self.editor.setTextCursor(cursor)
        self.status_label.setText(f"Replaced {count} occurrence(s)")

    # ── Snippet insertion ─────────────────────────────────────────────────────

    def _build_insert_menu(self) -> QMenu:
        menu = QMenu(self)
        for label, text in COMMON_SNIPPETS:
            action = menu.addAction(label)
            action.triggered.connect(
                lambda checked=False, snippet_label=label, snippet_text=text:
                self.insert_snippet(snippet_label, snippet_text)
            )
        return menu

    def insert_snippet(self, label: str, text: str) -> None:
        response = QMessageBox.question(
            self,
            "Insert common",
            f"Insert '{label}' into the editor?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        cursor = self.editor.textCursor()
        full_text = f"\n{text}\n"
        cursor.insertText(full_text)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()


# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    splash_started = time.monotonic()
    splash = QSplashScreen(_build_splash_pixmap())
    splash.showMessage(
        "Starting GLE Editor...",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        QColor("#153b66"),
    )
    splash.show()
    app.processEvents()

    window = GleApp()
    window.show()

    remaining = 2.5 - (time.monotonic() - splash_started)
    while remaining > 0:
        app.processEvents()
        time.sleep(min(0.01, remaining))
        remaining = 2.5 - (time.monotonic() - splash_started)

    splash.finish(window)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
