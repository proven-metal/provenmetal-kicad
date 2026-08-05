"""Put the plugin package on sys.path for the test run (works under unittest and
pytest, no install needed)."""

import os
import sys

_PLUGIN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "plugin"))
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
