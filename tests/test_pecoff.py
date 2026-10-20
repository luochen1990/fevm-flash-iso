# 职责边界: PE/COFF 头解析与 PE32+ x64 校验测试 (校验清单 #2 的单元层,
# 覆盖 m-2 的 OptionalHeader Magic / SizeOfHeaders 健全性)。

"""pecoff 测试。"""

import struct
from pathlib import Path

import pytest

from fevm_flash_iso.errors import ValidationError
from fevm_flash_iso.pecoff import PE32_PLUS_MAGIC, parse_pe_header, validate_efi_amd64
from fevm_flash_iso.synth import fake_efi_bytes


def _header_bytes(machine: int, magic: int, size_of_headers: int, size: int = 0x200) -> bytes:
    """确定性构造 PE 头样本 (offset: 0x40=PE 签名, 0x58=Magic, 0x94=SizeOfHeaders)."""
    buf = bytearray(size)
    buf[0:2] = b"MZ"
    struct.pack_into("<I", buf, 0x3C, 0x40)
    buf[0x40:0x44] = b"PE\x00\x00"
    struct.pack_into("<H", buf, 0x44, machine)
    struct.pack_into("<H", buf, 0x58, magic)
    struct.pack_into("<I", buf, 0x94, size_of_headers)
    return bytes(buf)


def test_parse_pe_header_good() -> None:
    r = parse_pe_header(fake_efi_bytes())
    assert r is not None
    assert r.machine == 0x8664
    assert r.optional_magic == PE32_PLUS_MAGIC
    assert r.size_of_headers == 0x200


def test_parse_pe_header_wrong_arch() -> None:
    r = parse_pe_header(fake_efi_bytes(machine=0x014C))
    assert r is not None
    assert r.machine == 0x014C


@pytest.mark.parametrize(
    "data",
    [
        b"",  # 空
        b"XX" + b"\x00" * 100,  # 无 MZ
        b"MZ",  # 头部截断 (读不到 e_lfanew)
        b"MZ" + b"\x00" * 0x3C + (0xFFFF).to_bytes(4, "little") + b"\x00" * 16,  # e_lfanew 越界
        # 无 PE 签名
        b"MZ" + b"\x00" * 0x3C + (0x40).to_bytes(4, "little") + b"NOTPE\x00\x00" + b"\x00" * 8,
    ],
)
def test_parse_pe_header_invalid(data: bytes) -> None:
    assert parse_pe_header(data) is None


def test_validate_efi_amd64_ok(tmp_path: Path) -> None:
    efi = tmp_path / "ok.efi"
    efi.write_bytes(fake_efi_bytes())
    validate_efi_amd64(efi, role="测试")


def test_validate_efi_amd64_bad_signature(tmp_path: Path) -> None:
    bad = tmp_path / "bad.efi"
    bad.write_bytes(b"garbage not a pe")
    with pytest.raises(ValidationError, match="PE/COFF"):
        validate_efi_amd64(bad, role="测试")


def test_validate_efi_amd64_wrong_machine(tmp_path: Path) -> None:
    bad = tmp_path / "i386.efi"
    bad.write_bytes(fake_efi_bytes(machine=0x014C))
    with pytest.raises(ValidationError, match="0x014C"):
        validate_efi_amd64(bad, role="测试")


def test_validate_efi_amd64_pe32_magic_rejected(tmp_path: Path) -> None:
    """m-2: OptionalHeader Magic 必须是 PE32+ (0x20B), PE32 (0x10B) 拒绝."""
    bad = tmp_path / "pe32.efi"
    bad.write_bytes(_header_bytes(machine=0x8664, magic=0x10B, size_of_headers=0x100))
    with pytest.raises(ValidationError, match="PE32"):
        validate_efi_amd64(bad, role="测试")


def test_validate_efi_amd64_headers_exceed_file_rejected(tmp_path: Path) -> None:
    """m-2: SizeOfHeaders 超过文件长度 => 截断/伪体, 拒绝."""
    bad = tmp_path / "truncated.efi"
    bad.write_bytes(_header_bytes(machine=0x8664, magic=PE32_PLUS_MAGIC, size_of_headers=0x10000))
    with pytest.raises(ValidationError, match="伪体"):
        validate_efi_amd64(bad, role="测试")


def test_validate_efi_amd64_random_pseudo_body_rejected(tmp_path: Path) -> None:
    """m-2: "MZ+PE 头后随机填充" 的伪体 (OptionalHeader 是垃圾) 必须被拒.
    用确定性字节构造, 避免随机样本偶然通过."""
    pseudo = bytearray(b"\xAA" * 0x200)
    pseudo[0:2] = b"MZ"
    struct.pack_into("<I", pseudo, 0x3C, 0x40)
    pseudo[0x40:0x44] = b"PE\x00\x00"
    struct.pack_into("<H", pseudo, 0x44, 0x8664)
    bad = tmp_path / "pseudo.efi"
    bad.write_bytes(bytes(pseudo))
    with pytest.raises(ValidationError):
        validate_efi_amd64(bad, role="测试")
