"""Build a lightweight "HEIC to JPG.app" launcher (macOS only).

The bundle contains only a shell script, an Info.plist and an icon. The
script runs main.py from this project folder with the project's .venv, so
edits to the code take effect the next time you open the app, with no
rebuild needed. Re-run this only if you move the project folder.

Usage:
    .venv/bin/python make_launcher.py [destination folder]
"""

import os
import plistlib
import shutil
import subprocess
import sys
import tempfile

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)

APP_NAME = "HEIC to JPG"
VERSION = "1.0"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLE_ID = "local.heictojpg.heic-to-jpg"

LAUNCHER_SCRIPT = """#!/bin/bash
# Lightweight launcher: runs the live source in the project folder.
PROJECT_DIR={project_dir}
LOG_FILE="$HOME/Library/Logs/HEIC to JPG.log"

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$PROJECT_DIR" 2>/dev/null || {{
    osascript -e 'display alert "HEIC to JPG" message "Project folder not found:\\n'"$PROJECT_DIR"'\\n\\nRun make_launcher.py again from the project folder."'
    exit 1
}}

if [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
    PYTHON="$PROJECT_DIR/.venv/bin/python"
else
    PYTHON="$(command -v python3)"
fi

if ! "$PYTHON" -c "import PySide6, PIL, pillow_heif" >/dev/null 2>&1; then
    "$PYTHON" -m pip install -q -r "$PROJECT_DIR/requirements.txt" >>"$LOG_FILE" 2>&1
fi

"$PYTHON" "$PROJECT_DIR/main.py" >>"$LOG_FILE" 2>&1
STATUS=$?

if [ $STATUS -ne 0 ]; then
    osascript -e 'display alert "HEIC to JPG quit unexpectedly" message "Details are in ~/Library/Logs/HEIC to JPG.log"'
fi

exit $STATUS
"""


def draw_icon(size=1024):
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)

    margin = size * 0.1
    rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    radius = rect.width() * 0.225

    gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    gradient.setColorAt(0, QColor("#FFB347"))
    gradient.setColorAt(1, QColor("#F2652A"))

    shape = QPainterPath()
    shape.addRoundedRect(rect, radius, radius)
    painter.fillPath(shape, QBrush(gradient))

    highlight = QLinearGradient(rect.topLeft(), rect.center())
    highlight.setColorAt(0, QColor(255, 255, 255, 50))
    highlight.setColorAt(1, QColor(255, 255, 255, 0))
    painter.fillPath(shape, QBrush(highlight))

    unit = rect.width() / 100
    origin = rect.topLeft()

    def point(x, y):
        return QPointF(origin.x() + x * unit, origin.y() + y * unit)

    # Photo frame with a sun and mountains.
    frame = QPainterPath()
    frame.addRoundedRect(QRectF(point(20, 16), point(80, 60)), 6 * unit, 6 * unit)
    painter.fillPath(frame, QColor("#FFFFFF"))

    painter.setClipPath(frame)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#FFC93C"))
    painter.drawEllipse(point(64, 29), 6 * unit, 6 * unit)

    mountains = QPainterPath()
    mountains.moveTo(point(20, 60))
    mountains.lineTo(point(40, 34))
    mountains.lineTo(point(54, 50))
    mountains.lineTo(point(62, 42))
    mountains.lineTo(point(80, 60))
    mountains.closeSubpath()
    painter.setBrush(QColor("#F2652A"))
    painter.drawPath(mountains)
    painter.setClipping(False)

    # "JPG" label.
    font = QFont("Helvetica Neue")
    font.setPixelSize(int(20 * unit))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#FFFFFF"))
    painter.drawText(QRectF(point(0, 62), point(100, 88)), Qt.AlignCenter, "JPG")

    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(QColor(0, 0, 0, 30), size * 0.004))
    painter.drawPath(shape)
    painter.end()

    return image


def build_icns(image, destination):
    iconset = tempfile.mkdtemp(suffix=".iconset")

    try:
        for base in [16, 32, 128, 256, 512]:
            for scale in [1, 2]:
                pixels = base * scale
                suffix = "@2x" if scale == 2 else ""
                scaled = image.scaled(pixels, pixels, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                scaled.save(os.path.join(iconset, f"icon_{base}x{base}{suffix}.png"))

        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", destination], check=True)
    finally:
        shutil.rmtree(iconset, ignore_errors=True)


def build_app(destination_dir):
    app_path = os.path.join(destination_dir, f"{APP_NAME}.app")
    contents = os.path.join(app_path, "Contents")
    macos_dir = os.path.join(contents, "MacOS")
    resources_dir = os.path.join(contents, "Resources")

    if os.path.exists(app_path):
        shutil.rmtree(app_path)

    os.makedirs(macos_dir)
    os.makedirs(resources_dir)

    build_icns(draw_icon(), os.path.join(resources_dir, "AppIcon.icns"))

    launcher_path = os.path.join(macos_dir, "launcher")
    quoted_dir = "'" + SCRIPT_DIR.replace("'", "'\\''") + "'"

    with open(launcher_path, "w", encoding="utf-8") as file:
        file.write(LAUNCHER_SCRIPT.format(project_dir=quoted_dir))

    os.chmod(launcher_path, 0o755)

    with open(os.path.join(contents, "Info.plist"), "wb") as file:
        plistlib.dump({
            "CFBundleName": APP_NAME,
            "CFBundleDisplayName": APP_NAME,
            "CFBundleIdentifier": BUNDLE_ID,
            "CFBundleExecutable": "launcher",
            "CFBundleIconFile": "AppIcon",
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
        }, file)

    subprocess.run(["touch", app_path], check=False)

    return app_path


def main():
    if sys.platform != "darwin":
        print("The launcher is macOS-only.")
        sys.exit(1)

    destination = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else SCRIPT_DIR
    QGuiApplication(sys.argv[:1] + ["-platform", "offscreen"])

    app_path = build_app(destination)
    print("Created:", app_path)
    print("It always runs the code in:", SCRIPT_DIR)


if __name__ == "__main__":
    main()
