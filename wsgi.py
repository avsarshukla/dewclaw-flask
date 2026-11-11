"""PythonAnywhere WSGI reference file. Path: dewclaw-flask."""
import sys

path = "/home/avsar/dewclaw-flask"
if path not in sys.path:
    sys.path.insert(0, path)

from app import app as application  # noqa: E402,F401
