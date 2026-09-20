# HEIC to JPG Converter

A fast, private desktop app that converts HEIC and HEIF photos to high-quality JPEG files. Built with Python and PySide6, it keeps every image on your computer and supports convenient batch conversion.

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![PySide6](https://img.shields.io/badge/UI-PySide6-41CD52?logo=qt&logoColor=white)
![Platforms](https://img.shields.io/badge/platform-macOS%20%7C%20Windows%20%7C%20Linux-lightgrey)

## Features

- Drag and drop individual files or entire folders
- Convert batches in a background thread without freezing the interface
- Save beside the originals or choose an output folder
- High, balanced, and space-saving JPEG quality presets
- Preserve EXIF and ICC color-profile metadata when available
- Correct photo orientation automatically
- Safe, atomic output writes that do not leave partial files
- Avoid output-name collisions and choose how to handle existing files
- See progress and conversion status for every image

## Why this project?

HEIC is efficient, but it is not accepted everywhere. This app provides a simple offline workflow for creating broadly compatible JPEG copies without uploading personal photos to a website.

## Requirements

- Python 3.10 or newer
- macOS, Windows, or Linux with a desktop environment

## Quick start

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Windows (PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

```bash
python main.py
```

Drag images into the window (folders are also accepted), choose the output and quality options, then click **Convert images**. When saving beside the originals, `holiday.heic` becomes `holiday.jpg` in the same folder.

If a destination already exists, the app lets you replace it or skip it. Transparent images are flattened onto white because JPEG does not support transparency.

## Project structure

```text
.
├── main.py           # Desktop interface and conversion logic
├── requirements.txt  # Runtime dependencies
└── README.md
```

## How it works

`pillow-heif` registers HEIC/HEIF support with Pillow. Each image is orientation-corrected, converted to RGB, and written to a temporary JPEG before being atomically moved into place. Conversion runs on a Qt worker thread so the interface stays responsive during large batches.

## Quick verification

```bash
python -m py_compile main.py
```

Then start the app and convert a known HEIC image. Run the same conversion again to verify the overwrite prompt.

## Privacy

The application does not upload images or require an account. All conversion happens locally.
