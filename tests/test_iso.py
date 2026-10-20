# 职责边界: iso 自检逻辑测试 —— Platform Id 行解析 (纯函数) 与真实
# xorriso 集成 (无 El Torito 的 ISO 必须被拒 / 内嵌副本哈希不一致必须被拒)。

"""iso 自检测试。"""

import subprocess
from pathlib import Path

import pytest
from conftest import requires_build_tools

from fevm_flash_iso.errors import BuildError
from fevm_flash_iso.fatimg import build_fat_image
from fevm_flash_iso.iso import _has_efi_eltorito, build_iso, verify_iso
from fevm_flash_iso.model import BUILD_SPECS, FlashTarget

# xorriso -report_el_torito plain 的实测输出形态 (节选)
_EFI_REPORT = (
    "El Torito catalog  : 33  1\n"
    "El Torito images   :   N  Pltf  B   Emul  Ld_seg  Hdpt  Ldsiz         LBA\n"
    "El Torito boot img :   1  UEFI  y   none  0x0000  0x00  16384          34\n"
    "El Torito img path :   1  /efi.img\n"
)
_BIOS_ONLY_REPORT = (
    "El Torito images   :   N  Pltf  B   Emul  Ld_seg  Hdpt  Ldsiz         LBA\n"
    "El Torito boot img :   1  BIOS  y   none  0x0000  0x00      4          34\n"
    "El Torito img path :   1  /efi.img\n"
)
_NO_PATH_REPORT = (
    "El Torito images   :   N  Pltf  B   Emul  Ld_seg  Hdpt  Ldsiz         LBA\n"
    "El Torito boot img :   1  UEFI  y   none  0x0000  0x00  16384          34\n"
)


def test_platform_id_parsing_efi() -> None:
    """m-1: Platform Id 行解析 —— UEFI 项 + /efi.img 路径 => 通过."""
    assert _has_efi_eltorito(_EFI_REPORT) is True


def test_platform_id_parsing_bios_only_rejected() -> None:
    """只有 BIOS 平台引导项 (无 EFI/UEFI) => 拒绝."""
    assert _has_efi_eltorito(_BIOS_ONLY_REPORT) is False


def test_platform_id_parsing_missing_img_path_rejected() -> None:
    """有 UEFI 项但引导镜像路径不是 /efi.img => 拒绝."""
    assert _has_efi_eltorito(_NO_PATH_REPORT) is False


@pytest.mark.parametrize(
    ("report", "expected"),
    [(_EFI_REPORT, True), (_BIOS_ONLY_REPORT, False), (_NO_PATH_REPORT, False), ("", False)],
)
def test_platform_id_parsing_property(report: str, expected: bool) -> None:
    assert _has_efi_eltorito(report) is expected


@requires_build_tools
def test_verify_rejects_iso_without_eltorito(tmp_path: Path) -> None:
    """集成: 无 El Torito 记录的普通 ISO 必须被自检拒绝."""
    isoroot = tmp_path / "isoroot"
    isoroot.mkdir()
    (isoroot / "dummy.txt").write_text("x", encoding="ascii")
    plain = tmp_path / "plain.iso"
    subprocess.run(
        ["xorriso", "-as", "mkisofs", "-quiet", "-volid", "PLAIN", "-o", str(plain), str(isoroot)],
        check=True, capture_output=True, text=True,
    )
    fake_fat = tmp_path / "whatever.img"
    fake_fat.write_bytes(b"not relevant")
    with pytest.raises(BuildError, match="El Torito"):
        verify_iso(plain, fake_fat, [], tmp_path)


@requires_build_tools
def test_verify_rejects_hash_mismatch(tmp_path: Path) -> None:
    """集成: 内嵌 efi.img 与源 FAT 镜像哈希不一致 => 拒绝 (写入损坏)."""
    spec = BUILD_SPECS[FlashTarget.EC]
    stage1, stage2 = tmp_path / "s1", tmp_path / "s2"
    stage1.mkdir()
    stage2.mkdir()
    (stage1 / "seed.txt").write_text("one", encoding="ascii")
    (stage2 / "seed.txt").write_text("two", encoding="ascii")
    img1, img2 = tmp_path / "a.img", tmp_path / "b.img"
    build_fat_image(img1, stage1, spec)
    build_fat_image(img2, stage2, spec)

    isoroot = tmp_path / "isoroot"
    isoroot.mkdir()
    isoroot.joinpath("efi.img").write_bytes(img1.read_bytes())
    iso = tmp_path / "mismatch.iso"
    build_iso(isoroot, iso, "MISMATCH")
    with pytest.raises(BuildError, match="哈希不一致"):
        verify_iso(iso, img2, [], tmp_path)
