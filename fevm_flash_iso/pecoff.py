# 职责边界: PE/COFF 头解析与 x64 EFI 自检 (最小 IO + 纯解析)。
# 契约 (防什么事故): 防止把非 EFI 或非 AMD64 的二进制当作引导 Shell 或
# 刷写工具打进镜像 —— 那会造出 "ISO 能引导但 Shell 起不来 / 刷写工具
# 在此平台无法执行" 的废盘。只解析头部签名与 Machine 字段, 不验证节表
# 与签名证书。

"""PE/COFF 头校验: MZ -> e_lfanew -> PE\\\\0\\\\0 -> Machine."""

from pathlib import Path

from .errors import ValidationError
from .model import PE_MACHINE_AMD64

_MZ = b"MZ"
_PE_SIG = b"PE\x00\x00"
_LFANEW_OFFSET = 0x3C


def parse_pe_machine(data: bytes) -> int | None:
    """从文件头字节解析 Machine 字段; 任一环节不合法返回 None."""
    if len(data) < 0x40 or data[:2] != _MZ:
        return None
    e_lfanew = int.from_bytes(data[_LFANEW_OFFSET : _LFANEW_OFFSET + 4], "little")
    if e_lfanew < 0 or e_lfanew + 6 > len(data):
        return None
    if data[e_lfanew : e_lfanew + 4] != _PE_SIG:
        return None
    return int.from_bytes(data[e_lfanew + 4 : e_lfanew + 6], "little")


def validate_efi_amd64(path: Path, *, role: str) -> None:
    """契约: path 必须是 PE32+ EFI 应用且 Machine=0x8664 (AMD64), 否则抛
    ValidationError (fail fast, 不把可疑二进制带进产物)."""
    data = path.read_bytes()
    machine = parse_pe_machine(data)
    if machine is None:
        raise ValidationError(
            f"{role} {path.name} 不是合法 PE/COFF 文件 (MZ/PE 签名缺失或头部截断)",
            "该 EFI 文件可能损坏或下载不完整; 请重新解包固件包或更换来源",
        )
    if machine != PE_MACHINE_AMD64:
        raise ValidationError(
            f"{role} {path.name} 的 PE Machine=0x{machine:04X}, 不是 AMD64 (0x8664) EFI 程序",
            "本管线只支持 x64 EFI; 确认拿到的固件包是 x64 版本",
        )
