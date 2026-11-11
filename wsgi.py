"""PythonAnywhere WSGI reference file.

On PythonAnywhere, the actual WSGI config is edited via the Web tab,
not this file. This file exists so the path and import are documented
in the repo.
"""
import sys

path = "/home/YOUR_USERNAME/dewclaw"
if path not in sys.path:
    sys.path.insert(0, path)

from app import app as application  # noqa: E402,F401
