"""
workers/__init__.py
===================

This empty file transforms the workers/ directory into a Python package.

A "package" in Python is simply a folder that contains an
__init__.py file. This allows importing internal modules with the notation:

    from workers.camera_worker import CameraWorker
    from workers.processing_worker import ProcessingWorker

Without this file, Python would not recognize workers/ as a package
and the imports above would fail with ModuleNotFoundError.

Modules contained in this package:
    - camera_worker.py    → CameraWorker(QThread): webcam frame capture
    - processing_worker.py → ProcessingWorker(QThread): MediaPipe + goniometry
"""
