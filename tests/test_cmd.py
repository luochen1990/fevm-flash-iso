# 职责边界: cmd.run_ok 的超时路径测试 (n-3) —— 外部工具卡死时转
# BuildError 而非让 CLI 永久挂起。

"""cmd 超时测试。"""

import subprocess

import pytest

import fevm_flash_iso.cmd as cmd_mod
from fevm_flash_iso.errors import BuildError

_TIMEOUT = cmd_mod.COMMAND_TIMEOUT_SECONDS


def _raise_timeout(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
    raise subprocess.TimeoutExpired(cmd=["stub"], timeout=_TIMEOUT)


def test_run_ok_timeout_becomes_build_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """monkeypatch 全局 subprocess.run (与 cmd 模块同一模块对象)."""
    monkeypatch.setattr(subprocess, "run", _raise_timeout)
    with pytest.raises(BuildError, match="超时"):
        cmd_mod.run_ok(["sleep", "999"])


def test_run_ok_timeout_message_contains_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", _raise_timeout)
    with pytest.raises(BuildError, match="xorriso"):
        cmd_mod.run_ok(["xorriso", "-as", "mkisofs"])
