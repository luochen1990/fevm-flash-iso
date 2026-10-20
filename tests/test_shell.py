# 职责边界: UEFI Shell 获取逻辑测试 (内置资产 / --shell-efi 覆盖 / 自检)。

"""shell 获取逻辑测试。"""

from pathlib import Path

import pytest

from fevm_flash_iso.errors import ValidationError
from fevm_flash_iso.shell import default_shell_path, resolve_shell_efi
from fevm_flash_iso.synth import fake_efi_bytes


def test_default_asset_exists_and_is_x64() -> None:
    """仓库内置资产必须存在且通过 PE/COFF AMD64 自检 (入库前自检的回归)."""
    path = default_shell_path()
    assert path.is_file()
    assert resolve_shell_efi(None) == path


def test_override_with_valid_shell(tmp_path: Path) -> None:
    custom = tmp_path / "CustomShell.efi"
    custom.write_bytes(fake_efi_bytes(size=4096))
    assert resolve_shell_efi(custom) == custom


def test_override_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValidationError) as exc:
        resolve_shell_efi(tmp_path / "ghost.efi")
    assert "--shell-efi" in exc.value.what


def test_override_not_a_pe(tmp_path: Path) -> None:
    bad = tmp_path / "shell.txt"
    bad.write_text("not an efi", encoding="ascii")
    with pytest.raises(ValidationError, match="UEFI Shell"):
        resolve_shell_efi(bad)
