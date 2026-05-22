# Register pytest-asyncio explicitly so async tests work even when
# PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 is set (to block ROS2 launch_testing).
pytest_plugins = ["pytest_asyncio"]
