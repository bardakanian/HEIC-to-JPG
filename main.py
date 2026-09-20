"""A polished desktop utility for converting HEIC/HEIF images to JPEG."""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QSizePolicy, QStyle, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

SUPPORTED_EXTENSIONS = {".heic", ".heif"}


@dataclass(frozen=True)
class ConversionJob:
    source: Path
    destination: Path


def human_file_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def convert_image(source: Path, destination: Path, quality: int, preserve_metadata: bool) -> None:
    """Convert atomically so a failed operation never leaves a partial JPG."""
    temporary_path: Path | None = None
    try:
        with Image.open(source) as image:
            image.load()
            image = ImageOps.exif_transpose(image)
            save_options: dict[str, object] = {
                "quality": quality,
                "subsampling": 0 if quality >= 90 else 2,
                "optimize": True,
            }
            if preserve_metadata:
                if exif := image.info.get("exif"):
                    save_options["exif"] = exif
                if icc_profile := image.info.get("icc_profile"):
                    save_options["icc_profile"] = icc_profile

            if image.mode in ("RGBA", "LA") or (
                image.mode == "P" and "transparency" in image.info
            ):
                rgba = image.convert("RGBA")
                converted = Image.new("RGB", rgba.size, "white")
                converted.paste(rgba, mask=rgba.getchannel("A"))
            else:
                converted = image.convert("RGB")

            destination.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{destination.stem}-", suffix=".tmp.jpg", dir=destination.parent
            )
            os.close(descriptor)
            temporary_path = Path(temporary_name)
            converted.save(temporary_path, "JPEG", **save_options)
            os.replace(temporary_path, destination)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


class ConversionWorker(QObject):
    progress = Signal(int, str, str)
    finished = Signal(int, int, list)

    def __init__(self, jobs: list[ConversionJob], quality: int,
                 preserve_metadata: bool, overwrite: bool) -> None:
        super().__init__()
        self.jobs = jobs
        self.quality = quality
        self.preserve_metadata = preserve_metadata
        self.overwrite = overwrite

    @Slot()
    def run(self) -> None:
        converted = 0
        skipped = 0
        failures: list[str] = []
        for index, job in enumerate(self.jobs):
            if job.destination.exists() and not self.overwrite:
                skipped += 1
                self.progress.emit(index, "Skipped", "Destination already exists")
                continue
            try:
                convert_image(job.source, job.destination, self.quality, self.preserve_metadata)
                converted += 1
                self.progress.emit(index, "Complete", str(job.destination))
            except Exception as error:  # Continue processing the rest of the batch.
                message = str(error) or error.__class__.__name__
                failures.append(f"{job.source.name}: {message}")
                self.progress.emit(index, "Failed", message)
        self.finished.emit(converted, skipped, failures)


class DropPanel(QFrame):
    files_dropped = Signal(list)
    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("dropPanel")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(116)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(5)
        icon = QLabel("+")
        icon.setObjectName("dropIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Drop HEIC files here")
        title.setObjectName("dropTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel("or click to browse your computer")
        subtitle.setObjectName("mutedLabel")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addWidget(subtitle)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_drag_state(True)

    def dragLeaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._set_drag_state(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_drag_state(False)
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        self.files_dropped.emit(paths)
        event.acceptProposedAction()

    def _set_drag_state(self, active: bool) -> None:
        self.setProperty("dragActive", active)
        self.style().unpolish(self)
        self.style().polish(self)


class HeicToJpgWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        register_heif_opener()
        self.selected_files: list[Path] = []
        self.output_folder: Path | None = None
        self.worker_thread: QThread | None = None
        self.worker: ConversionWorker | None = None
        self.setWindowTitle("HEIC to JPG")
        self.resize(980, 720)
        self.setMinimumSize(760, 620)
        self._build_interface()
        self._apply_style()
        self._refresh_controls()

    def _build_interface(self) -> None:
        central = QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)
        page = QVBoxLayout(central)
        page.setContentsMargins(36, 28, 36, 28)
        page.setSpacing(18)

        header = QHBoxLayout()
        header.setSpacing(14)
        mark = QLabel("H")
        mark.setObjectName("brandMark")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(46, 46)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        title = QLabel("HEIC to JPG")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Fast, private image conversion — everything stays on your computer.")
        subtitle.setObjectName("mutedLabel")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addWidget(mark)
        header.addLayout(titles)
        header.addStretch()
        page.addLayout(header)

        self.drop_panel = DropPanel()
        self.drop_panel.clicked.connect(self.select_files)
        self.drop_panel.files_dropped.connect(self.add_files)
        page.addWidget(self.drop_panel)

        files_header = QHBoxLayout()
        files_title = QLabel("Files")
        files_title.setObjectName("sectionTitle")
        self.file_count = QLabel("0 images")
        self.file_count.setObjectName("countPill")
        files_header.addWidget(files_title)
        files_header.addWidget(self.file_count)
        files_header.addStretch()
        self.remove_button = QPushButton("Remove selected")
        self.remove_button.setObjectName("textButton")
        self.remove_button.clicked.connect(self.remove_selected)
        self.clear_button = QPushButton("Clear all")
        self.clear_button.setObjectName("textButton")
        self.clear_button.clicked.connect(self.clear_files)
        files_header.addWidget(self.remove_button)
        files_header.addWidget(self.clear_button)
        page.addLayout(files_header)

        self.table = QTableWidget(0, 3)
        self.table.setObjectName("fileTable")
        self.table.setHorizontalHeaderLabels(["FILE", "SIZE", "STATUS"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(170)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._refresh_controls)
        page.addWidget(self.table, 1)

        settings = QFrame()
        settings.setObjectName("settingsCard")
        settings_layout = QVBoxLayout(settings)
        settings_layout.setContentsMargins(18, 14, 18, 14)
        settings_layout.setSpacing(12)
        settings_title = QLabel("Conversion settings")
        settings_title.setObjectName("sectionTitle")
        settings_layout.addWidget(settings_title)
        setting_row = QHBoxLayout()
        setting_row.setSpacing(12)
        self.location_button = QPushButton("Save beside originals")
        self.location_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        self.location_button.clicked.connect(self.choose_output_folder)
        self.location_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.quality_combo = QComboBox()
        self.quality_combo.addItem("High quality · 95%", 95)
        self.quality_combo.addItem("Balanced · 85%", 85)
        self.quality_combo.addItem("Smaller file · 75%", 75)
        self.quality_combo.setMinimumWidth(170)
        self.metadata_checkbox = QCheckBox("Keep metadata")
        self.metadata_checkbox.setChecked(True)
        setting_row.addWidget(self.location_button)
        setting_row.addWidget(self.quality_combo)
        setting_row.addWidget(self.metadata_checkbox)
        settings_layout.addLayout(setting_row)
        page.addWidget(settings)

        footer = QHBoxLayout()
        footer.setSpacing(14)
        status_stack = QVBoxLayout()
        status_stack.setSpacing(5)
        self.status_label = QLabel("Add HEIC or HEIF images to begin")
        self.status_label.setObjectName("statusLabel")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(5)
        self.progress.setVisible(False)
        status_stack.addWidget(self.status_label)
        status_stack.addWidget(self.progress)
        footer.addLayout(status_stack, 1)
        self.convert_button = QPushButton("Convert images")
        self.convert_button.setObjectName("primaryButton")
        self.convert_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward))
        self.convert_button.clicked.connect(self.start_conversion)
        self.convert_button.setMinimumWidth(180)
        footer.addWidget(self.convert_button)
        page.addLayout(footer)

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QWidget#root { background: #f5f7fb; color: #18202b; }
            QLabel { font-size: 13px; }
            QLabel#pageTitle { font-size: 25px; font-weight: 700; color: #111827; }
            QLabel#sectionTitle { font-size: 14px; font-weight: 650; color: #1f2937; }
            QLabel#mutedLabel { color: #667085; }
            QLabel#brandMark { background: #2563eb; color: white; border-radius: 13px;
                               font-size: 21px; font-weight: 800; }
            QLabel#dropIcon { color: #2563eb; font-size: 28px; font-weight: 400; }
            QLabel#dropTitle { color: #1d2939; font-size: 15px; font-weight: 650; }
            QLabel#countPill { color: #475467; background: #e9edf5; border-radius: 10px;
                              padding: 3px 9px; font-size: 11px; }
            QLabel#statusLabel { color: #475467; }
            QFrame#dropPanel { background: #f8faff; border: 2px dashed #a7b7d8; border-radius: 14px; }
            QFrame#dropPanel:hover, QFrame#dropPanel[dragActive="true"] {
                background: #eef4ff; border-color: #2563eb; }
            QFrame#settingsCard { background: white; border: 1px solid #e1e6ef; border-radius: 12px; }
            QTableWidget { background: white; alternate-background-color: #fafbfc; border: 1px solid #e1e6ef;
                           border-radius: 12px; selection-background-color: #e9f0ff;
                           selection-color: #18202b; outline: none; }
            QTableWidget::item { border: none; padding: 9px; }
            QHeaderView::section { background: #f8fafc; color: #667085; border: none;
                                   border-bottom: 1px solid #e1e6ef; padding: 9px;
                                   font-size: 10px; font-weight: 700; }
            QPushButton, QComboBox { background: white; color: #344054; border: 1px solid #d0d5dd;
                                     border-radius: 8px; padding: 8px 12px; }
            QPushButton:hover, QComboBox:hover { border-color: #98a2b3; background: #fafafa; }
            QPushButton:disabled { color: #98a2b3; background: #f2f4f7; border-color: #e4e7ec; }
            QPushButton#textButton { border: none; background: transparent; color: #475467; padding: 5px 7px; }
            QPushButton#textButton:hover { color: #1d4ed8; background: #edf3ff; }
            QPushButton#textButton:disabled { color: #b3bac5; background: transparent; }
            QPushButton#primaryButton { background: #2563eb; color: white; border: none;
                                        padding: 11px 20px; font-weight: 650; }
            QPushButton#primaryButton:hover { background: #1d4ed8; }
            QPushButton#primaryButton:disabled { background: #aab7d1; color: #eef2f8; }
            QCheckBox { color: #475467; spacing: 7px; }
            QProgressBar { background: #e4e7ec; border: none; border-radius: 2px; }
            QProgressBar::chunk { background: #2563eb; border-radius: 2px; }
            QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
            QScrollBar::handle:vertical { background: #c7ced9; min-height: 28px; border-radius: 4px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

    @Slot()
    def select_files(self) -> None:
        filenames, _ = QFileDialog.getOpenFileNames(
            self, "Select HEIC or HEIF images", "",
            "HEIC images (*.heic *.heif *.HEIC *.HEIF);;All files (*)")
        if filenames:
            self.add_files([Path(name) for name in filenames])

    @Slot(list)
    def add_files(self, paths: list[Path]) -> None:
        candidates: list[Path] = []
        for path in paths:
            if path.is_dir():
                try:
                    candidates.extend(child for child in path.iterdir()
                                      if child.suffix.lower() in SUPPORTED_EXTENSIONS)
                except OSError:
                    pass
            else:
                candidates.append(path)
        valid = [path.resolve() for path in candidates
                 if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS]
        invalid_count = len(candidates) - len(valid)
        existing = set(self.selected_files)
        added = [path for path in valid if path not in existing]
        self.selected_files.extend(added)
        self._populate_table()
        message = f"Added {len(added)} image{'s' if len(added) != 1 else ''}"
        if invalid_count:
            message += f" · ignored {invalid_count} unsupported file{'s' if invalid_count != 1 else ''}"
        elif not added and valid:
            message = "Those images are already in the list"
        elif not valid:
            message = "No HEIC or HEIF images were found"
        self.status_label.setText(message)

    def _populate_table(self) -> None:
        self.table.setRowCount(len(self.selected_files))
        for row, path in enumerate(self.selected_files):
            try:
                size = human_file_size(path.stat().st_size)
            except OSError:
                size = "Unavailable"
            name = QTableWidgetItem(path.name)
            name.setToolTip(str(path))
            status = QTableWidgetItem("Ready")
            status.setForeground(QColor("#2563eb"))
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem(size))
            self.table.setItem(row, 2, status)
            self.table.setRowHeight(row, 44)
        count = len(self.selected_files)
        self.file_count.setText(f"{count} image{'s' if count != 1 else ''}")
        self._refresh_controls()

    @Slot()
    def remove_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            del self.selected_files[row]
        self._populate_table()
        self.status_label.setText(f"Removed {len(rows)} image{'s' if len(rows) != 1 else ''}")

    @Slot()
    def clear_files(self) -> None:
        self.selected_files.clear()
        self._populate_table()
        self.status_label.setText("Add HEIC or HEIF images to begin")

    @Slot()
    def choose_output_folder(self) -> None:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Output location")
        dialog.setText("Where should converted JPG files be saved?")
        beside = dialog.addButton("Beside originals", QMessageBox.ButtonRole.AcceptRole)
        choose = dialog.addButton("Choose folder…", QMessageBox.ButtonRole.ActionRole)
        dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.exec()
        if dialog.clickedButton() == beside:
            self.output_folder = None
            self.location_button.setText("Save beside originals")
            self.location_button.setToolTip("")
        elif dialog.clickedButton() == choose:
            folder = QFileDialog.getExistingDirectory(self, "Choose output folder")
            if folder:
                self.output_folder = Path(folder)
                self.location_button.setText(f"Save to: {self.output_folder.name}")
                self.location_button.setToolTip(str(self.output_folder))

    def _destination_for(self, source: Path) -> Path:
        folder = self.output_folder or source.parent
        return folder / f"{source.stem}.jpg"

    def _create_jobs(self) -> list[ConversionJob]:
        """Create destinations, avoiding name collisions in a shared output folder."""
        jobs: list[ConversionJob] = []
        reserved: set[str] = set()
        for source in self.selected_files:
            destination = self._destination_for(source)
            candidate = destination
            number = 2
            while str(candidate).casefold() in reserved:
                candidate = destination.with_name(f"{destination.stem} ({number}){destination.suffix}")
                number += 1
            reserved.add(str(candidate).casefold())
            jobs.append(ConversionJob(source, candidate))
        return jobs

    @Slot()
    def start_conversion(self) -> None:
        if not self.selected_files or self.worker_thread is not None:
            return
        jobs = self._create_jobs()
        existing = sum(job.destination.exists() for job in jobs)
        overwrite = False
        if existing:
            answer = QMessageBox.question(
                self, "Replace existing files?",
                f"{existing} JPG file{'s' if existing != 1 else ''} already "
                f"{'exist' if existing != 1 else 'exists'}. Replace {'them' if existing != 1 else 'it'}?\n\n"
                "Choose No to skip existing files.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No |
                QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Cancel:
                return
            overwrite = answer == QMessageBox.StandardButton.Yes

        self._set_busy(True)
        self.progress.setRange(0, len(jobs))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.status_label.setText(f"Converting 0 of {len(jobs)} images…")
        for row in range(self.table.rowCount()):
            self.table.item(row, 2).setText("Waiting")
            self.table.item(row, 2).setForeground(QColor("#667085"))

        self.worker_thread = QThread(self)
        self.worker = ConversionWorker(jobs, int(self.quality_combo.currentData()),
                                       self.metadata_checkbox.isChecked(), overwrite)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self._cleanup_worker)
        self.worker_thread.start()

    @Slot(int, str, str)
    def _on_progress(self, row: int, state: str, detail: str) -> None:
        item = self.table.item(row, 2)
        item.setText(state)
        item.setToolTip(detail)
        colors = {"Complete": "#16803a", "Skipped": "#b54708", "Failed": "#b42318"}
        item.setForeground(QColor(colors.get(state, "#667085")))
        self.progress.setValue(row + 1)
        self.status_label.setText(f"Converting {row + 1} of {len(self.selected_files)} images…")

    @Slot(int, int, list)
    def _on_finished(self, converted: int, skipped: int, failures: list[str]) -> None:
        parts = [f"{converted} converted"]
        if skipped:
            parts.append(f"{skipped} skipped")
        if failures:
            parts.append(f"{len(failures)} failed")
        summary = " · ".join(parts)
        self.status_label.setText(summary)
        if failures:
            details = "\n".join(failures[:12])
            if len(failures) > 12:
                details += f"\n…and {len(failures) - 12} more"
            QMessageBox.warning(self, "Conversion finished with errors", f"{summary}\n\n{details}")
        else:
            QMessageBox.information(self, "Conversion complete", summary.capitalize() + ".")

    @Slot()
    def _cleanup_worker(self) -> None:
        if self.worker_thread is not None:
            self.worker_thread.deleteLater()
        self.worker = None
        self.worker_thread = None
        self._set_busy(False)
        self.progress.setVisible(False)

    def _set_busy(self, busy: bool) -> None:
        self.drop_panel.setEnabled(not busy)
        self.table.setEnabled(not busy)
        self.location_button.setEnabled(not busy)
        self.quality_combo.setEnabled(not busy)
        self.metadata_checkbox.setEnabled(not busy)
        self.convert_button.setEnabled(not busy and bool(self.selected_files))
        self.clear_button.setEnabled(not busy and bool(self.selected_files))
        self.remove_button.setEnabled(not busy and bool(self.table.selectionModel().selectedRows()))

    @Slot()
    def _refresh_controls(self) -> None:
        busy = self.worker_thread is not None
        self.convert_button.setEnabled(not busy and bool(self.selected_files))
        self.clear_button.setEnabled(not busy and bool(self.selected_files))
        self.remove_button.setEnabled(not busy and bool(self.table.selectionModel().selectedRows()))

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self.worker_thread is not None and self.worker_thread.isRunning():
            QMessageBox.information(self, "Conversion in progress", "Please wait for conversion to finish.")
            event.ignore()
            return
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("HEIC to JPG")
    app.setOrganizationName("HEIC to JPG")
    app.setStyle("Fusion")
    window = HeicToJpgWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
