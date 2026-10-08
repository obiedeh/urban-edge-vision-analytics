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


import pytest  # noqa: E402


@pytest.fixture
def make_mp4(tmp_path):
    """Factory writing a tiny MPEG-4 file (``frames`` frames at ``fps``) for upload tests."""

    def _make(name: str = "clip.mp4", frames: int = 10, fps: int = 25, size=(64, 48)):
        import av
        import numpy as np

        path = tmp_path / name
        container = av.open(str(path), "w")
        stream = container.add_stream("mpeg4", rate=fps)
        stream.width, stream.height, stream.pix_fmt = size[0], size[1], "yuv420p"
        for i in range(frames):
            array = np.full((size[1], size[0], 3), (i * 23) % 255, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(array, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
        container.close()
        return path

    return _make
