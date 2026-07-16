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
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtCore import QEvent, QRectF, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QInputDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplashScreen,
    QSpinBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

APP_ORG = "GLE-Editor"
APP_NAME = "GleEditorApp"
APP_VERSION = "1.0.19"
RECENT_FILES_KEY = "recent_files"
MAX_RECENT_FILES = 20
ABOUT_TEXT = (
    "GLE Editor\n"
    "Stephen Blundell\n"
    "University of Oxford\n"
    "Department of Physics\n"
    f"Version {APP_VERSION}\n"
    "July 2026"
)

COMMON_BIN_DIRS = ["/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin"]

# Common locations where pdflatex / TeX Live binaries live on macOS
TEX_BIN_DIRS = [
    "/Library/TeX/texbin",                         # MacTeX universal symlink
    "/usr/local/texlive/2024/bin/universal-darwin",
    "/usr/local/texlive/2023/bin/universal-darwin",
    "/usr/local/texlive/2022/bin/universal-darwin",
    "/usr/local/texlive/2024/bin/x86_64-darwin",
    "/usr/local/texlive/2023/bin/x86_64-darwin",
    "/usr/local/texlive/2022/bin/x86_64-darwin",
    "/opt/homebrew/bin",
    "/usr/local/bin",
]

GLE_KEYWORDS_XML_SOURCE: Path | None = None
GLE_KEYWORDS_SOURCE_MODE = "fallback"


def _default_gle_keywords() -> dict[str, list[str]]:
    """Fallback keywords used when gle_npp.xml is unavailable in packaged builds."""
    return {
        "Words1": [
            "add", "aline", "amove", "arc", "arrow", "bar", "begin", "bezier", "box", "cap",
            "circle", "clip", "closepath", "color", "command", "curve", "data", "define", "dist",
            "ellipse", "else", "end", "end if", "fill", "font", "for", "from", "graph", "grid",
            "gsave", "grestore", "hei", "if", "include", "join", "just", "justify", "left", "let",
            "line", "lstyle", "lwidth", "marker", "max", "min", "name", "next", "off", "on",
            "origin", "path", "postscript", "radius", "return", "right", "rline", "rmove", "rotate",
            "save", "scale", "set", "shift", "size", "smooth", "step", "stroke", "table", "text",
            "then", "title", "to", "translate", "width", "write",
        ],
        "Words2": [
            "xaxis", "xlabels", "xnames", "xplaces", "xsubticks", "xticks", "xtitle",
            "x2axis", "x2labels", "x2names", "x2places", "x2subticks", "x2ticks", "x2title",
        ],
        "Words3": [
            "yaxis", "ylabels", "ynames", "yplaces", "ysubticks", "yticks", "ytitle",
            "y2axis", "y2labels", "y2names", "y2places", "y2subticks", "y2ticks", "y2title",
            "key", "sub",
        ],
    }


class GleTextEdit(QPlainTextEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._kill_to_eol_shortcut = QShortcut(QKeySequence("Meta+K"), self)
        self._kill_to_eol_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self._kill_to_eol_shortcut.activated.connect(self.kill_to_end_of_line)

    def kill_to_end_of_line(self) -> None:
        cursor = self.textCursor()
        if cursor.hasSelection():
            cursor.removeSelectedText()
        else:
            cursor.movePosition(
                QTextCursor.MoveOperation.EndOfBlock,
                QTextCursor.MoveMode.KeepAnchor,
            )
            cursor.removeSelectedText()
        self.setTextCursor(cursor)

    def keyPressEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.MetaModifier and event.key() == Qt.Key.Key_K:
            self.kill_to_end_of_line()
            return
        super().keyPressEvent(event)


def _load_gle_keywords() -> dict[str, list[str]]:
    """Parse assets/gle_npp.xml and return keyword lists keyed by Words1/Words2/Words3."""
    global GLE_KEYWORDS_XML_SOURCE
    global GLE_KEYWORDS_SOURCE_MODE
    GLE_KEYWORDS_XML_SOURCE = None
    GLE_KEYWORDS_SOURCE_MODE = "fallback"

    candidate_rel_paths = [
        Path("assets/gle_npp.xml"),
        Path("assets/gle-npp.xml"),
        Path("gle_npp.xml"),
        Path("gle-npp.xml"),
    ]

    for base in _resource_search_dirs():
        for rel in candidate_rel_paths:
            xml_path = base / rel
            if not xml_path.exists():
                continue
            try:
                tree = ET.parse(str(xml_path))
                root = tree.getroot()
                result: dict[str, list[str]] = {}
                for kw in root.iter("Keywords"):
                    name = kw.get("name", "")
                    text = (kw.text or "").replace("\r\n", "\n").replace("\r", "\n")
                    words = [w.strip() for w in text.split("\n") if w.strip()]
                    if words:
                        result[name] = words
                if result:
                    GLE_KEYWORDS_XML_SOURCE = xml_path
                    GLE_KEYWORDS_SOURCE_MODE = "xml"
                    return result
            except Exception:
                continue

    GLE_KEYWORDS_SOURCE_MODE = "fallback"
    return _default_gle_keywords()


class GleSyntaxHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for GLE files based on gle_npp.xml keyword definitions."""

    def __init__(self, document) -> None:
        super().__init__(document)
        self._rules: list[tuple[re.Pattern, QTextCharFormat]] = []
        self._build_rules()

    @staticmethod
    def _fmt(color_hex: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(f"#{color_hex}"))
        if bold:
            fmt.setFontWeight(QFont.Weight.Bold)
        if italic:
            fmt.setFontItalic(True)
        return fmt

    def _build_rules(self) -> None:
        kw = _load_gle_keywords()

        # Quoted strings – purple; matched first so keywords inside strings aren't coloured
        self._rules.append((
            re.compile(r'"[^"]*"'),
            self._fmt("8000FF"),
        ))

        # Words1 – blue bold (GLE commands)
        words1 = sorted(set(kw.get("Words1", [])), key=len, reverse=True)
        if words1:
            pat = "|".join(r"\b" + re.escape(w) + r"\b" for w in words1)
            self._rules.append((re.compile(pat, re.IGNORECASE), self._fmt("0000FF", bold=True)))

        # Words2 + Words3 – dark red bold (axis / graph keywords)
        words23 = sorted(set(kw.get("Words2", []) + kw.get("Words3", [])), key=len, reverse=True)
        if words23:
            pat = "|".join(r"\b" + re.escape(w) + r"\b" for w in words23)
            self._rules.append((re.compile(pat, re.IGNORECASE), self._fmt("800040", bold=True)))

        # Numbers – red
        self._rules.append((
            re.compile(r"\b\d+(\.\d+)?([eE][+-]?\d+)?\b"),
            self._fmt("CC0000"),
        ))

        # Comments: everything from ! to end of line – green italic (applied last so it wins)
        self._rules.append((
            re.compile(r"!.*$"),
            self._fmt("008000", italic=True),
        ))

    def highlightBlock(self, text: str) -> None:
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


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
        Path("icon.iconset/icon_32x32.png"),
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


def _load_app_icon() -> QIcon:
    pix = _load_icon_pixmap(128)
    if pix.isNull():
        return QIcon()
    return QIcon(pix)


def _load_about_icon_pixmap(size: int) -> QPixmap:
    relative_candidates = [
        Path("assets/icon.png"),
        Path("icon.png"),
        Path("icon.icns"),
        Path("icon.iconset/icon_512x512.png"),
        Path("icon.iconset/icon_256x256.png"),
        Path("icon.iconset/icon_128x128.png"),
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

    # Final fallback: reuse the generic app icon search logic.
    return _load_icon_pixmap(size)


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
            "QPushButton { border: 1px solid #888; padding: 9px 18px; border-radius: 3px; }"
        )
        self._app = app

        layout = QVBoxLayout(self)
        layout.setContentsMargins(27, 21, 27, 21)
        layout.setSpacing(9)

        about_icon = QLabel()
        about_pix = _load_about_icon_pixmap(324)
        if not about_pix.isNull():
            about_icon.setPixmap(about_pix)
        about_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_icon.setFixedHeight(336)
        layout.addWidget(about_icon)

        label = QLabel(ABOUT_TEXT)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setFont(QFont("Helvetica", 17))
        layout.addWidget(label)

        # GLE configuration button
        btn_config = QPushButton("Configure GLE path...")
        btn_config.clicked.connect(self._configure_gle)
        layout.addWidget(btn_config)

        # Display current GLE path if available
        if app and app._gle_executable:
            info_label = QLabel(f"GLE path: {app._gle_executable}")
            info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            info_label.setFont(QFont("Helvetica", 14))
            info_label.setStyleSheet("color: #666;")
            layout.addWidget(info_label)

        btn_close = QPushButton("Close window")
        btn_close.clicked.connect(self.close)
        btn_close.setStyleSheet(
            "QPushButton { background-color: #c62828; color: white; border-color: #8e0000; }"
            "QPushButton:pressed { background-color: #8e0000; }"
        )
        layout.addWidget(btn_close)

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
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.grabGesture(Qt.GestureType.PinchGesture)
        self._zoom = 1.5
        self._view_zoom = 1.0
        self._min_view_zoom = 0.25
        self._max_view_zoom = 8.0
        self._grid_mode = 0  # 0=off, 1=1cm grid, 2=1cm+5cm overlay grid
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
            if self._grid_mode != 0:
                self._draw_grid()
            self.resetTransform()
            self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self.scale(self._view_zoom, self._view_zoom)
        except Exception as e:
            print(f"PDF viewer error: {e}")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._scene.sceneRect().isEmpty():
            self.resetTransform()
            self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self.scale(self._view_zoom, self._view_zoom)

    def _in_draw_mode(self) -> bool:
        return any(
            (
                self._amove_mode,
                self._aline_mode,
                self._box_mode,
                self._box_fill_mode,
                self._circle_mode,
                self._circle_fill_mode,
                self._ellipse_mode,
                self._ellipse_fill_mode,
                self._text_mode,
                self._arrow_end_mode,
                self._arrow_start_mode,
                self._arrow_both_mode,
            )
        )

    def _set_view_zoom(self, target_zoom: float, anchor_center: bool = False) -> None:
        target_zoom = max(self._min_view_zoom, min(target_zoom, self._max_view_zoom))
        if abs(target_zoom - self._view_zoom) < 1e-9:
            return
        factor = target_zoom / self._view_zoom
        self._view_zoom = target_zoom
        if anchor_center:
            self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
            self.scale(factor, factor)
            self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        else:
            self.scale(factor, factor)

    def zoom_in(self) -> None:
        self._set_view_zoom(self._view_zoom * 1.15)

    def zoom_out(self) -> None:
        self._set_view_zoom(self._view_zoom / 1.15)

    def _pan_by_pixels(self, dx: int, dy: int) -> None:
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + dx)
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + dy)

    def wheelEvent(self, event) -> None:
        if self._in_draw_mode() or self._scene.sceneRect().isEmpty():
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return
        if delta > 0:
            self.zoom_in()
        else:
            self.zoom_out()
        event.accept()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal, Qt.Key.Key_Up):
            if key == Qt.Key.Key_Up:
                self._pan_by_pixels(0, -30)
            else:
                self.zoom_in()
            event.accept()
            return
        if key in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            self.zoom_out()
            event.accept()
            return
        if key == Qt.Key.Key_Down:
            self._pan_by_pixels(0, 30)
            event.accept()
            return
        if key == Qt.Key.Key_Left:
            self._pan_by_pixels(-30, 0)
            event.accept()
            return
        if key == Qt.Key.Key_Right:
            self._pan_by_pixels(30, 0)
            event.accept()
            return
        super().keyPressEvent(event)

    def _handle_pinch_gesture(self, gesture) -> bool:
        if self._scene.sceneRect().isEmpty() or self._in_draw_mode():
            return False
        factor = float(gesture.scaleFactor())
        if factor <= 0:
            return False
        self._set_view_zoom(self._view_zoom * factor)
        return True

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.Gesture:
            pinch = event.gesture(Qt.GestureType.PinchGesture)
            if pinch and self._handle_pinch_gesture(pinch):
                return True
        elif event.type() == QEvent.Type.NativeGesture:
            try:
                gesture_type = event.gestureType()
                # macOS trackpad pinch reports ZoomNativeGesture with a small delta value
                if str(gesture_type).endswith("ZoomNativeGesture"):
                    scale_delta = float(event.value())
                    self._set_view_zoom(self._view_zoom * (1.0 + scale_delta))
                    return True
            except Exception:
                pass
        return super().event(event)

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
        # Backward-compatible bridge for older call sites.
        self.set_grid_mode(1 if visible else 0)

    def set_grid_mode(self, mode: int) -> None:
        self._grid_mode = max(0, min(2, int(mode)))
        if self._grid_mode != 0:
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

        if self._grid_mode >= 1:
            self._draw_grid_layer(step_cm=1.0, color=QColor(30, 80, 200, 90), width=1, z_value=10)

        if self._grid_mode >= 2:
            self._draw_grid_layer(step_cm=5.0, color=QColor(30, 80, 200, 150), width=2, z_value=11)

    def _draw_grid_layer(self, step_cm: float, color: QColor, width: int, z_value: float) -> None:
        w, h = self._pixmap_size
        if w == 0 or h == 0:
            return

        step = step_cm * 28.3465 * self._zoom
        pen = QPen(color)
        pen.setCosmetic(True)
        pen.setWidth(width)

        x = step
        while x < w:
            item = self._scene.addLine(x, 0, x, h, pen)
            item.setZValue(z_value)
            self._grid_items.append(item)
            x += step

        y = h - step
        while y > 0:
            item = self._scene.addLine(0, y, w, y, pen)
            item.setZValue(z_value)
            self._grid_items.append(item)
            y -= step


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
        self._line_spin_syncing = False
        self.fillcolor = "grey20"
        self._grid_mode = 0
        self._about_popup: AboutPopup | None = None

        # Autosave 1 second after the last keystroke
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(1000)
        self._autosave_timer.timeout.connect(self._autosave)

        self._build_ui()
        self._apply_syntax_status_hint()
        self._initialize_gle_path()
        self._restore_state()
        self.editor.moveCursor(QTextCursor.MoveOperation.End)
        self.editor.setFocus()

    def _apply_syntax_status_hint(self) -> None:
        if GLE_KEYWORDS_XML_SOURCE is not None:
            hint = f"GLE syntax XML loaded: {GLE_KEYWORDS_XML_SOURCE.name}"
            detail = str(GLE_KEYWORDS_XML_SOURCE)
        elif GLE_KEYWORDS_SOURCE_MODE == "fallback":
            hint = "GLE syntax XML not found (fallback keywords)"
            detail = "Using built-in fallback keywords. Place gle_npp.xml (or gle-npp.xml) in assets/ or app root."
        else:
            hint = "GLE syntax XML not found"
            detail = "Place gle_npp.xml (or gle-npp.xml) in assets/ or app root."

        self.status_label.setText(hint)
        self.status_label.setToolTip(detail)

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

        btn_load_recent = QPushButton("Load Recent")
        btn_load_recent.clicked.connect(self.load_recent_file)
        btn_load_recent.setStyleSheet("background-color: #7fffd4;")  # aquamarine
        bar.addWidget(btn_load_recent)

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

        self.btn_grid = QPushButton("Grid: Off")
        self.btn_grid.clicked.connect(self.cycle_grid_mode)
        self.btn_grid.setStyleSheet("QPushButton { background-color: #d8b4fe; color: #111; }")
        bar.addWidget(self.btn_grid)

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

        self.line_box = QWidget()
        line_box_layout = QHBoxLayout(self.line_box)
        line_box_layout.setContentsMargins(6, 2, 6, 2)
        line_box_layout.setSpacing(4)

        self.line_label = QLabel("Line:")
        line_box_layout.addWidget(self.line_label)

        self.line_spin = QSpinBox()
        self.line_spin.setRange(1, 1)
        self.line_spin.setValue(1)
        self.line_spin.setFixedWidth(90)
        line_box_layout.addWidget(self.line_spin)

        self._set_line_spin_color(editing=False)
        line_edit = self.line_spin.lineEdit()
        if line_edit is not None:
            line_edit.textEdited.connect(self._on_line_spin_text_edited)
            line_edit.returnPressed.connect(self._jump_cursor_to_line_from_spin)
        bar.addWidget(self.line_box)

        btn_about = QPushButton("About")
        btn_about.clicked.connect(self.show_about)
        btn_about.setStyleSheet("background-color: #ffeef4;")
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

        self.btn_set_color = QPushButton("set color")
        self.btn_set_color.clicked.connect(self.choose_color)
        self.btn_set_color.setStyleSheet(
            "QPushButton { background-color: #ffd6a5; }"
            "QPushButton:pressed { background-color: #f4b183; }"
        )
        eb.addWidget(self.btn_set_color)

        self.btn_fill = QPushButton("Fill")
        self.btn_fill.clicked.connect(self.choose_fill)
        self.btn_fill.setStyleSheet(
            "QPushButton { background-color: #ffe4a1; }"
            "QPushButton:pressed { background-color: #f3cd6d; }"
        )
        eb.addWidget(self.btn_fill)

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

        self.editor = GleTextEdit()
        self.editor.setFont(QFont("Courier New", 11))
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.textChanged.connect(self._on_text_changed)
        self.editor.cursorPositionChanged.connect(self._sync_line_spin_from_cursor)
        splitter.addWidget(self.editor)
        self._highlighter = GleSyntaxHighlighter(self.editor.document())

        self.pdf_viewer = PdfViewer()
        splitter.addWidget(self.pdf_viewer)

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

        self._apply_grid_mode()
        self._sync_line_spin_from_cursor()

    def cycle_grid_mode(self) -> None:
        self._grid_mode = (self._grid_mode + 1) % 3
        self._apply_grid_mode()

    def _apply_grid_mode(self) -> None:
        self.pdf_viewer.set_grid_mode(self._grid_mode)

        if self._grid_mode == 0:
            self.btn_grid.setText("Grid: Off")
            self.btn_grid.setStyleSheet("QPushButton { background-color: #d8b4fe; color: #111; }")
        elif self._grid_mode == 1:
            self.btn_grid.setText("Grid: 1cm")
            self.btn_grid.setStyleSheet("QPushButton { background-color: #9c6ade; color: white; }")
        else:
            self.btn_grid.setText("Grid: 1cm+5cm")
            self.btn_grid.setStyleSheet("QPushButton { background-color: #5f2ea8; color: white; }")

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

    def _normalise_recent_path(self, path: Path) -> Path:
        expanded = path.expanduser()
        if expanded.is_absolute():
            return expanded.resolve(strict=False)
        return (Path.cwd() / expanded).resolve(strict=False)

    def _recent_files(self) -> list[Path]:
        value = self.settings.value(RECENT_FILES_KEY, [])
        if value is None:
            raw_items = []
        elif isinstance(value, str):
            raw_items = [value] if value else []
        else:
            raw_items = list(value)

        recent: list[Path] = []
        seen: set[str] = set()
        for item in raw_items:
            if not item:
                continue
            path = self._normalise_recent_path(Path(str(item)))
            key = os.path.normcase(str(path))
            if key in seen:
                continue
            seen.add(key)
            recent.append(path)
            if len(recent) >= MAX_RECENT_FILES:
                break
        return recent

    def _set_recent_files(self, paths: list[Path]) -> None:
        recent: list[Path] = []
        seen: set[str] = set()
        for path in paths:
            normalised = self._normalise_recent_path(path)
            key = os.path.normcase(str(normalised))
            if key in seen:
                continue
            seen.add(key)
            recent.append(normalised)
            if len(recent) >= MAX_RECENT_FILES:
                break

        self.settings.setValue(RECENT_FILES_KEY, [str(path) for path in recent])
        self.settings.sync()

    def _remember_recent_file(self, path: Path) -> None:
        self._set_recent_files([path] + self._recent_files())

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
        self._sync_line_spin_from_cursor()
        self._autosave_dirty = False
        if self._write_current():
            self._remember_recent_file(new_path)
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

    def load_recent_file(self) -> None:
        recent = self._recent_files()
        if not recent:
            QMessageBox.information(
                self,
                "Load Recent",
                "No recent GLE files have been recorded yet.",
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Load Recent")

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        label = QLabel("Choose a recent GLE file:")
        layout.addWidget(label)

        file_list = QListWidget(dialog)
        file_list.addItems([str(path) for path in recent])
        file_list.setCurrentRow(0)
        file_list.setAlternatingRowColors(True)
        file_list.setMinimumWidth(760)
        file_list.setMinimumHeight(max(180, min(440, 26 * len(recent) + 8)))
        file_list.itemActivated.connect(lambda _item: dialog.accept())
        layout.addWidget(file_list)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel,
            dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        file_list.setFocus()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected = file_list.currentItem()
            if selected is not None:
                self._load_path(Path(selected.text()))

    def _load_path(self, path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as e:
            QMessageBox.critical(self, "Load error", str(e))
            return

        self._current_path = path
        self.settings.setValue("last_dir", str(path.parent))
        self._remember_recent_file(path)

        # Populate editor without triggering autosave
        self._autosave_timer.stop()
        self.editor.blockSignals(True)
        self.editor.setPlainText(text)
        self.editor.blockSignals(False)
        self._sync_line_spin_from_cursor()
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
            if self._write_current():
                self._remember_recent_file(self._current_path)
            return
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
        if self._write_current():
            self._remember_recent_file(self._current_path)

    def _write_current(self) -> bool:
        if self._current_path is None:
            return False
        try:
            self._current_path.write_text(self.editor.toPlainText(), encoding="utf-8")
            self._autosave_dirty = False
            self.status_label.setText(f"Saved {self._current_path.name}")
            return True
        except Exception as e:
            QMessageBox.critical(self, "Save error", str(e))
            return False

    def _on_text_changed(self) -> None:
        self._autosave_dirty = True
        self._sync_line_spin_from_cursor()
        if self._current_path is not None:
            self._autosave_timer.start()   # resets the 1-second window

    def _sync_line_spin_from_cursor(self) -> None:
        max_line = max(1, self.editor.blockCount())
        current_line = self.editor.textCursor().blockNumber() + 1
        self._line_spin_syncing = True
        try:
            self.line_spin.setRange(1, max_line)
            self.line_spin.setValue(current_line)
        finally:
            self._line_spin_syncing = False

    def _on_line_spin_text_edited(self, _text: str) -> None:
        self._set_line_spin_color(editing=True)

    def _set_line_spin_color(self, editing: bool) -> None:
        box_color = "#ffff99" if editing else "#ffffff"
        self.line_box.setStyleSheet(
            "background-color: " + box_color + ";"
            "border: 1px solid #888;"
            "border-radius: 4px;"
        )
        self.line_spin.setStyleSheet(
            "QSpinBox { background-color: #ffffff; border: 1px solid #888; border-radius: 3px; }"
            "QSpinBox QLineEdit { background-color: #ffffff; }"
        )

    def _jump_cursor_to_line_from_spin(self) -> None:
        if self._line_spin_syncing:
            return

        max_line = max(1, self.editor.blockCount())
        target_line = max(1, min(self.line_spin.value(), max_line))

        block = self.editor.document().findBlockByNumber(target_line - 1)
        if not block.isValid():
            return

        cursor = self.editor.textCursor()
        cursor.setPosition(block.position() + block.length() - 1)
        self.editor.setTextCursor(cursor)
        self.editor.centerCursor()
        self._set_line_spin_color(editing=False)
        self.editor.setFocus()

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

    def _build_subprocess_env(self) -> dict[str, str]:
        """Return an env dict with GLE and TeX binary directories prepended to PATH."""
        env = os.environ.copy()
        path_entries: list[str] = []

        # GLE's own directory
        if self._gle_executable:
            path_entries.append(str(Path(self._gle_executable).parent))

        # Common tool dirs (includes homebrew, /usr/local/bin, etc.)
        path_entries.extend(COMMON_BIN_DIRS)

        # TeX Live / MacTeX dirs so GLE can invoke pdflatex
        path_entries.extend(TEX_BIN_DIRS)

        # Preserve whatever PATH was already set
        current_path = env.get("PATH", "")
        if current_path:
            path_entries.append(current_path)

        env["PATH"] = ":".join(dict.fromkeys(path_entries))
        return env

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

        try:
            result = subprocess.run(
                [self._gle_executable, "-device", "pdf", str(self._current_path)],
                capture_output=True,
                text=True,
                cwd=str(self._current_path.parent),
                env=self._build_subprocess_env(),
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
                env=self._build_subprocess_env(),
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
        if self._about_popup is not None and self._about_popup.isVisible():
            self._about_popup.close()
            self._about_popup = None
            return

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
        text = f"\namove {x1:.2f} {y1:.2f}\ncircle {radius:.2f} fill {self.fillcolor}\n"
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
        text = f"\namove {x1:.2f} {y1:.2f}\nellipse {dx:.2f} {dy:.2f} fill {self.fillcolor}\n"
        cursor = self.editor.textCursor()
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        self.run_gle()

    def insert_box_fill(self, x1: float, y1: float, x2: float, y2: float) -> None:
        # Insert amove and box with fill option on their own lines
        dx = x2 - x1
        dy = y2 - y1
        text = f"\namove {x1:.2f} {y1:.2f}\nbox {dx:.2f} {dy:.2f} fill {self.fillcolor}\n"
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

    def choose_color(self) -> None:
        color = QColorDialog.getColor(QColor("#ADFF2F"), self, "Select color")
        if not color.isValid():
            return

        hex_code = f"#{color.red():02X}{color.green():02X}{color.blue():02X}"
        cursor = self.editor.textCursor()
        cursor.insertText(f"set color {hex_code}\n")
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def choose_fill(self) -> None:
        options = ["black", "white", "grey20", "grey5", "colour"]
        choice, ok = QInputDialog.getItem(
            self,
            "Choose fill",
            "Fill colour:",
            options,
            options.index(self.fillcolor) if self.fillcolor in options else 2,
            False,
        )
        if not ok:
            return

        chosen = choice.strip().lower()
        if chosen in {"colour", "color"}:
            color = QColorDialog.getColor(QColor("#ADFF2F"), self, "Select fill color")
            if not color.isValid():
                return
            self.fillcolor = f"#{color.red():02X}{color.green():02X}{color.blue():02X}"
        else:
            self.fillcolor = chosen

        self.status_label.setText(f"Fill set to {self.fillcolor}")

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
