# 职责边界: golden 测试 —— 合法合成包 -> CLI 全流程 -> 两个 ISO 产物,
# 并做独立于 CLI 内部自检的外部验证 (xorriso -indev / mdir)。需要外部
# 工具 (nix develop), 缺失时整体跳过。

"""golden: 全链路构建测试。"""

import subprocess
from pathlib import Path

import pytest
from conftest import requires_build_tools

from fevm_flash_iso import cli

pytestmark = requires_build_tools

BIOS_ISO = "TESTX1_FLASH_BIOS_V1.06.iso"
EC_ISO = "TESTX1_FLASH_EC_V9.4.0.1.29F.iso"


def _mdir(image: Path, rel: str) -> bool:
    proc = subprocess.run(
        ["mdir", "-i", str(image), f"::/{rel}"], capture_output=True, text=True, check=False
    )
    return proc.returncode == 0


def test_golden_build_both_isos(pkg: Path, out_dir: Path) -> None:
    rc = cli.main([str(pkg), "-o", str(out_dir)])
    assert rc == 0
    bios_iso = out_dir / BIOS_ISO
    ec_iso = out_dir / EC_ISO
    assert bios_iso.is_file()
    assert ec_iso.is_file()
    # 默认 stage 用临时目录, out_dir 不留中间物
    assert sorted(p.name for p in out_dir.iterdir()) == [BIOS_ISO, EC_ISO]
    # 尺寸量级合理性: BIOS 盘 (64M FAT x2) > EC 盘 (8M FAT x2)
    assert bios_iso.stat().st_size > ec_iso.stat().st_size
    assert bios_iso.stat().st_size > 128 * 1024 * 1024
    assert ec_iso.stat().st_size > 16 * 1024 * 1024


def test_golden_isos_readable_with_eltorito(pkg: Path, out_dir: Path) -> None:
    assert cli.main([str(pkg), "-o", str(out_dir)]) == 0
    for iso in (out_dir / BIOS_ISO, out_dir / EC_ISO):
        proc = subprocess.run(
            ["xorriso", "-indev", str(iso), "-report_el_torito", "plain"],
            capture_output=True, text=True, check=False,
        )
        assert proc.returncode == 0, proc.stderr
        combined = proc.stdout + proc.stderr
        assert "UEFI" in combined
        assert "/efi.img" in combined


def test_golden_keep_stage_layout(pkg: Path, out_dir: Path) -> None:
    """--keep-stage 保留中间物, 可直接用 mdir 验证 FAT 镜像内关键路径."""
    assert cli.main([str(pkg), "-o", str(out_dir), "--keep-stage"]) == 0
    fat_specs = {
        "bios": [
            "EFI/BOOT/BOOTX64.EFI", "startup.nsh", "README.txt",
            "0_Afu_Flash/Tools/AfuEfix64.efi", "0_Afu_Flash/Tools/nFlash.nsh",
            "0_Afu_Flash/TESTX1_FP11_STXH_TEST_S112_V1.06_M0TEST_8000_1_12_EC_V0.1.29_20260101.bin",
        ],
        "ec": [
            "EFI/BOOT/BOOTX64.EFI", "startup.nsh", "README.txt",
            "EC/FEC64.NSH", "EC/ifu.efi", "EC/uiset.ini", "EC/EC_TESTX1_V9_4_0_1_29F.bin",
            "EC/ChecksumF.txt",  # n-5: 随盘分发, 供人工比对
        ],
    }
    for kind, rels in fat_specs.items():
        image = out_dir / "stage" / kind / "isoroot" / "efi.img"
        assert image.is_file(), image
        for rel in rels:
            assert _mdir(image, rel), f"{kind} FAT 镜像缺少 {rel}"
        assert not _mdir(image, "NOPE.BIN")


def test_golden_default_out_dir_is_package_dist(pkg: Path) -> None:
    assert cli.main([str(pkg)]) == 0
    assert (pkg / "dist" / BIOS_ISO).is_file()
    assert (pkg / "dist" / EC_ISO).is_file()


def test_golden_cli_report(pkg: Path, out_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """构建完成后的摘要表 / ISO 内容清单 / 下一步提示 全部打印."""
    assert cli.main([str(pkg), "-o", str(out_dir)]) == 0
    out = capsys.readouterr().out
    for needle in (
        "TESTX1", "V1.06", "V0.1.29", "V9.4.0.1.29F",
        "checksum : deadbeef", "供人工比对",
        "EFI/BOOT/BOOTX64.EFI", "0_Afu_Flash", "FEC64.NSH",
        "下一步操作", "Ventoy", "F7", "5 秒", "断电",
    ):
        assert needle in out, f"stdout 缺少 {needle!r}"
    assert "警告" not in out  # 标准合成包不应有任何警告
