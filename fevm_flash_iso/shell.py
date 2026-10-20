# 职责边界: UEFI Shell 二进制的定位与自检。优先 --shell-efi 覆盖参数,
# 其次使用包内内置 assets/Shell.efi (edk2 UEFI Shell 2.2 X64, 来源与许
# 可见 assets/SHELL_SOURCE.md)。返回前一律做 PE/COFF AMD64 自检 ——
# 防止损坏/错架构的 Shell 造出 "ISO 引导后黑屏或 Shell 崩溃" 的废盘。

"""UEFI Shell 二进制定位与自检。"""

from pathlib import Path

from .errors import ValidationError
from .pecoff import validate_efi_amd64


def default_shell_path() -> Path:
    """包内内置 UEFI Shell 的路径 (随包分发, 可再分发许可)."""
    return Path(__file__).resolve().parent / "assets" / "Shell.efi"


def resolve_shell_efi(override: Path | None) -> Path:
    """返回可用的 UEFI Shell 路径: override 优先, 否则内置资产."""
    path = override if override is not None else default_shell_path()
    if not path.is_file():
        source = "--shell-efi 参数" if override is not None else "内置资产"
        raise ValidationError(
            f"UEFI Shell 文件不存在 ({source}): {path}",
            "提供正确的 edk2 UEFI Shell x64 EFI 文件路径 (--shell-efi <PATH>), "
            "或修复仓库/安装内缺失的 assets/Shell.efi",
        )
    validate_efi_amd64(path, role="UEFI Shell")
    return path
