# 职责边界: PE/COFF 头解析与 x64 EFI 自检 (最小 IO + 纯解析)。
# 契约 (防什么事故): 防止把非 EFI 或非 AMD64 的二进制当作引导 Shell 或
# 刷写工具打进镜像 —— 那会造出 "ISO 能引导但 Shell 起不来 / 刷写工具
# 在此平台无法执行" 的废盘; 也防止只有 6 字节合法头部的截断/伪体文件
# 混过校验 (OptionalHeader Magic 必须 PE32+, SizeOfHeaders 必须落在文件
# 长度内)。只解析头部字段, 不验证节表与签名证书。

"""PE/COFF 头校验: MZ -> e_lfanew -> PE\\\\0\\\\0 -> OptionalHeader."""

from dataclasses import dataclass
from pathlib import Path

from .errors import ValidationError
from .model import PE_MACHINE_AMD64

_MZ = b"MZ"
_PE_SIG = b"PE\x00\x00"
_LFANEW_OFFSET = 0x3C
_OPT_OFFSET = 24  # e_lfanew + 4 (签名) + 20 (FileHeader) = OptionalHeader 起始
_MAGIC_OFFSET = 0  # OptionalHeader.Magic
_SIZEOF_HEADERS_OFFSET = 60  # OptionalHeader.SizeOfHeaders (PE32+ 布局)
PE32_PLUS_MAGIC = 0x20B


@dataclass(frozen=True)
class PeHeader:
    """解析出的 PE 头关键字段."""

    machine: int
    optional_magic: int
    size_of_headers: int


def parse_pe_header(data: bytes) -> PeHeader | None:
    """从文件头字节解析关键字段; 任一环节不合法返回 None.

    偏移: e_lfanew+24 = OptionalHeader.Magic; e_lfanew+84 = SizeOfHeaders.
    """
    if len(data) < 0x40 or data[:2] != _MZ:
        return None
    e_lfanew = int.from_bytes(data[_LFANEW_OFFSET : _LFANEW_OFFSET + 4], "little")
    opt = e_lfanew + _OPT_OFFSET
    if opt + 2 > len(data) or data[e_lfanew : e_lfanew + 4] != _PE_SIG:
        return None
    if opt + _SIZEOF_HEADERS_OFFSET + 4 > len(data):
        return None
    return PeHeader(
        machine=int.from_bytes(data[e_lfanew + 4 : e_lfanew + 6], "little"),
        optional_magic=int.from_bytes(
            data[opt + _MAGIC_OFFSET : opt + _MAGIC_OFFSET + 2], "little"
        ),
        size_of_headers=int.from_bytes(
            data[opt + _SIZEOF_HEADERS_OFFSET : opt + _SIZEOF_HEADERS_OFFSET + 4], "little"
        ),
    )


def validate_efi_amd64(path: Path, *, role: str) -> None:
    """契约: path 必须是完整的 PE32+ EFI 应用且 Machine=0x8664 (AMD64),
    否则抛 ValidationError (fail fast, 不把可疑二进制带进产物)."""
    data = path.read_bytes()
    header = parse_pe_header(data)
    if header is None:
        raise ValidationError(
            f"{role} {path.name} 不是合法 PE/COFF 文件 (MZ/PE 签名缺失或头部截断)",
            "该 EFI 文件可能损坏或下载不完整; 请重新解包固件包或更换来源",
        )
    if header.machine != PE_MACHINE_AMD64:
        raise ValidationError(
            f"{role} {path.name} 的 PE Machine=0x{header.machine:04X}, "
            "不是 AMD64 (0x8664) EFI 程序",
            "本管线只支持 x64 EFI; 确认拿到的固件包是 x64 版本",
        )
    if header.optional_magic != PE32_PLUS_MAGIC:
        raise ValidationError(
            f"{role} {path.name} 的 OptionalHeader Magic=0x{header.optional_magic:04X}, "
            "不是 PE32+ (0x20B), EFI 应用必须是 PE32+ 格式",
            "该文件可能是 32 位 PE 或头部损坏的伪体文件; 请确认文件完整",
        )
    if header.size_of_headers > len(data):
        raise ValidationError(
            f"{role} {path.name} 的 SizeOfHeaders ({header.size_of_headers}) 超过文件长度 "
            f"({len(data)}), 是截断或随机填充的伪体文件",
            "该 EFI 文件不完整; 请重新解包固件包或更换来源",
        )
