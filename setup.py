"""
Build standalone .app bundle with py2app.

Uso:
    .venv/bin/python3 setup.py py2app
"""

import os

from setuptools import setup

APP = ["launcher.py"]


def collect_tree(src_root):
    """Restituisce una lista di tuple (dest_dir, [file...]) per py2app data_files,
    preservando la struttura di cartelle relativa a src_root."""
    entries = []
    for dirpath, _dirnames, filenames in os.walk(src_root):
        if not filenames:
            continue
        rel_dir = os.path.relpath(dirpath, os.path.dirname(src_root))
        files = [os.path.join(dirpath, f) for f in filenames]
        entries.append((rel_dir, files))
    return entries


DATA_FILES = collect_tree("templates") + collect_tree("vendor")

OPTIONS = {
    "argv_emulation": False,
    "packages": ["flask", "jinja2", "werkzeug", "markupsafe", "click", "itsdangerous", "blinker"],
    "includes": ["webview", "objc", "Foundation", "AppKit", "WebKit", "Quartz", "PyObjCTools", "core", "app"],
    "iconfile": "AppIcon.icns",
    "plist": {
        "CFBundleName": "Google Photos Takeout Fixer",
        "CFBundleDisplayName": "Google Photos Takeout Fixer",
        "CFBundleIdentifier": "com.ugopossenti.googlephotostakeoutfixer",
        "CFBundleVersion": "1.1.1",
        "CFBundleShortVersionString": "1.1.1",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
    },
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
