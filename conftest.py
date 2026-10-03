import os
import tempfile

# Register pytest-asyncio explicitly so async tests work even when
# PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 is set (to block ROS2 launch_testing).
pytest_plugins = ["pytest_asyncio.plugin"]

# Tests must never touch the developer's real config store or secret key.
# api.main reads these at import time, so they are set before any test module
# imports the app.
_TEST_DIR = tempfile.mkdtemp(prefix="urban-edge-tests-")
os.environ.setdefault("STORE_PATH", os.path.join(_TEST_DIR, "test-store.sqlite"))
os.environ.setdefault("URBAN_EDGE_SECRET_KEY_FILE", os.path.join(_TEST_DIR, "secret.key"))
os.environ.setdefault("URBAN_EDGE_AUTOSTART", "0")
