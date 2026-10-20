# 职责边界: PE/COFF 头解析与 AMD64 校验测试 (校验清单 #2 的单元层)。

"""pecoff 测试。"""

from pathlib import Path

import pytest

from fevm_flash_iso.errors import ValidationError
from fevm_flash_iso.pecoff import parse_pe_machine, validate_efi_amd64
from fevm_flash_iso.synth import fake_efi_bytes


def test_parse_pe_machine_good() -> None:
    assert parse_pe_machine(fake_efi_bytes()) == 0x8664


def test_parse_pe_machine_wrong_arch() -> None:
    assert parse_pe_machine(fake_efi_bytes(machine=0x014C)) == 0x014C


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
def test_parse_pe_machine_invalid(data: bytes) -> None:
    assert parse_pe_machine(data) is None


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
