# 职责边界: 包结构识别测试 (校验清单 #1: 自动识别 / 歧义 / 显式覆盖)。

"""discover 测试。"""

import shutil
from pathlib import Path

import pytest

from fevm_flash_iso import synth
from fevm_flash_iso.discover import discover
from fevm_flash_iso.errors import ValidationError


def _bios_dir(pkg: Path) -> Path:
    return pkg / synth.SynthOptions().bios_dir_name


def _ec_dir(pkg: Path) -> Path:
    return pkg / synth.SynthOptions().ec_dir_name


def test_discover_happy_path(pkg: Path) -> None:
    layout = discover(pkg, None, None)
    opts = synth.SynthOptions()
    assert layout.bios.bin_path.name == opts.bios_bin_name
    assert layout.bios.afu_efi.name == "AfuEfix64.efi"
    assert layout.bios.nflash_nsh.name == "nFlash.nsh"
    assert layout.ec.bin_path.name == opts.ec_bin_name
    assert layout.ec.ifu_efi.name == "ifu.efi"
    assert layout.ec.fec_nsh.name == "FEC64.NSH"
    assert layout.ec.uiset_ini is not None
    assert layout.ec.checksum_txt is not None


def test_discover_case_insensitive_filenames(pkg: Path) -> None:
    """Windows 打包的包常见大小写漂移, 识别必须不受影响."""
    bios = _bios_dir(pkg)
    shutil.move(bios / "Tools" / "AfuEfix64.efi", bios / "Tools" / "afuefix64.EFI")
    shutil.move(bios / "Tools" / "nFlash.nsh", bios / "Tools" / "nflash.NSH")
    layout = discover(pkg, None, None)
    assert layout.bios.afu_efi.name == "afuefix64.EFI"


def test_discover_root_missing(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="包根目录"):
        discover(tmp_path / "nope", None, None)


def test_discover_no_bios_dir(pkg: Path) -> None:
    shutil.rmtree(_bios_dir(pkg))
    with pytest.raises(ValidationError) as exc:
        discover(pkg, None, None)
    assert "BIOS" in exc.value.what
    assert "--bios-dir" in exc.value.hint


def test_discover_no_ec_dir(pkg: Path) -> None:
    shutil.rmtree(_ec_dir(pkg))
    with pytest.raises(ValidationError) as exc:
        discover(pkg, None, None)
    assert "EC" in exc.value.what
    assert "--ec-dir" in exc.value.hint


def test_discover_multiple_bios_dirs(pkg: Path) -> None:
    shutil.copytree(_bios_dir(pkg), pkg / "OTHER_2.00_BIOS")
    with pytest.raises(ValidationError) as exc:
        discover(pkg, None, None)
    assert "候选 BIOS" in exc.value.what
    assert "--bios-dir" in exc.value.hint


def test_discover_bios_dir_override_disambiguates(pkg: Path) -> None:
    extra = pkg / "OTHER_2.00_BIOS"
    shutil.copytree(_bios_dir(pkg), extra)
    layout = discover(pkg, extra, None)
    assert layout.bios.dir == extra


def test_discover_explicit_dir_missing_pieces(pkg: Path, tmp_path: Path) -> None:
    empty = tmp_path / "empty_bios"
    empty.mkdir()
    with pytest.raises(ValidationError) as exc:
        discover(pkg, empty, None)
    assert "缺少 BIOS 目录要素" in exc.value.what
    assert "Tools/AfuEfix64.efi" in exc.value.what


def test_discover_explicit_dir_not_exists(pkg: Path, tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="--bios-dir 指向的目录不存在"):
        discover(pkg, tmp_path / "ghost", None)


def test_discover_ambiguous_bins_in_dir(pkg: Path) -> None:
    extra_bin = _bios_dir(pkg) / "TESTX1_V9.99_extra.bin"
    extra_bin.write_bytes(b"MZ" + b"\x00" * 8 * 1024 * 1024)
    with pytest.raises(ValidationError, match="无法确定 BIOS 镜像"):
        discover(pkg, None, None)


def test_discover_ec_missing_ifu_skips_candidate(pkg: Path) -> None:
    (_ec_dir(pkg) / "ifu.efi").unlink()
    with pytest.raises(ValidationError) as exc:
        discover(pkg, None, None)
    assert "未识别出 EC" in exc.value.what
