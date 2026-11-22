"""Native library selection must work before scientific packages are imported."""

import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

from fairifier.utils import env_patch


def test_libstdcxx_preload_uses_base_environment_for_nested_venv(monkeypatch):
    monkeypatch.setattr(env_patch.sys, "platform", "linux")
    monkeypatch.setattr(env_patch.sys, "prefix", "/nested/venv")
    monkeypatch.setattr(env_patch.sys, "base_prefix", "/base/environment")
    monkeypatch.setattr(
        env_patch.os.path, "exists",
        lambda path: path == "/base/environment/lib/libstdc++.so.6",
    )
    load = Mock()
    monkeypatch.setattr(env_patch.ctypes, "CDLL", load)

    env_patch.apply_libstdcxx_fix()

    load.assert_called_once_with(
        "/base/environment/lib/libstdc++.so.6", mode=env_patch.ctypes.RTLD_GLOBAL
    )


def test_libstdcxx_preload_prefers_current_environment(monkeypatch):
    monkeypatch.setattr(env_patch.sys, "platform", "linux")
    monkeypatch.setattr(env_patch.sys, "prefix", "/current/environment")
    monkeypatch.setattr(env_patch.sys, "base_prefix", "/base/environment")
    monkeypatch.setattr(env_patch.os.path, "exists", lambda path: True)
    load = Mock()
    monkeypatch.setattr(env_patch.ctypes, "CDLL", load)

    env_patch.apply_libstdcxx_fix()

    load.assert_called_once_with(
        "/current/environment/lib/libstdc++.so.6", mode=env_patch.ctypes.RTLD_GLOBAL
    )


def test_libstdcxx_preload_keeps_non_linux_unchanged(monkeypatch):
    monkeypatch.setattr(env_patch.sys, "platform", "darwin")
    load = Mock()
    monkeypatch.setattr(env_patch.ctypes, "CDLL", load)

    env_patch.apply_libstdcxx_fix()

    load.assert_not_called()


def test_libstdcxx_preload_tries_base_when_current_library_cannot_load(monkeypatch, caplog):
    monkeypatch.setattr(env_patch.sys, "platform", "linux")
    monkeypatch.setattr(env_patch.sys, "prefix", "/current/environment")
    monkeypatch.setattr(env_patch.sys, "base_prefix", "/base/environment")
    monkeypatch.setattr(env_patch.os.path, "exists", lambda path: True)
    load = Mock(side_effect=[OSError("incompatible library"), object()])
    monkeypatch.setattr(env_patch.ctypes, "CDLL", load)

    with caplog.at_level("WARNING"):
        env_patch.apply_libstdcxx_fix()

    assert [call.args[0] for call in load.call_args_list] == [
        "/current/environment/lib/libstdc++.so.6",
        "/base/environment/lib/libstdc++.so.6",
    ]
    assert "incompatible library" in caplog.text


def test_libstdcxx_preload_without_bundled_libraries_is_a_noop(monkeypatch):
    monkeypatch.setattr(env_patch.sys, "platform", "linux")
    monkeypatch.setattr(env_patch.sys, "prefix", "/nested/venv")
    monkeypatch.setattr(env_patch.sys, "base_prefix", "/base/environment")
    monkeypatch.setattr(env_patch.os.path, "exists", lambda path: False)
    load = Mock()
    monkeypatch.setattr(env_patch.ctypes, "CDLL", load)

    env_patch.apply_libstdcxx_fix()

    load.assert_not_called()


def test_package_initializes_native_library_selection_before_optional_imports():
    # A fresh interpreter models the real CLI/API package-import boundary.
    # Stub the loader so this unit test does not load a native library.
    source = """
import sys
import types
calls = []
loader = types.ModuleType('fairifier.utils.env_patch')
loader.apply_libstdcxx_fix = lambda: calls.append('preload')
sys.modules['fairifier.utils.env_patch'] = loader
import fairifier
assert calls == ['preload'], calls
assert 'fitz' not in sys.modules
assert 'mem0' not in sys.modules
"""
    repo_root = Path(env_patch.__file__).resolve().parents[2]
    process_env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    process_env["PYTHONPATH"] = str(repo_root)

    result = subprocess.run(
        [sys.executable, "-c", source], cwd=repo_root, env=process_env,
        capture_output=True, text=True, timeout=20,
    )

    assert result.returncode == 0, result.stderr
