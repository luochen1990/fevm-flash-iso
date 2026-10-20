# 职责边界: 内容层校验测试 (校验清单 #2-#7: PE/尺寸/交叉引用/软一致性/
# ChecksumF 信息展示), 以及解析摘要的正确性。

"""validate 测试。"""

import shutil
from pathlib import Path

import pytest

from fevm_flash_iso import synth
from fevm_flash_iso.discover import discover
from fevm_flash_iso.errors import ValidationError
from fevm_flash_iso.validate import FirmwareSummary, validate


def _validate(pkg: Path) -> FirmwareSummary:
    return validate(discover(pkg, None, None))


def test_validate_happy_path(pkg: Path) -> None:
    s = _validate(pkg)
    assert s.model == "TESTX1"
    assert s.bios_bin.bios_display == "V1.06"
    assert s.bios_bin.embedded_ec_display == "V0.1.29"
    assert s.ec_bin.display == "V9.4.0.1.29F"
    assert s.ec_consistent is True  # 0.1.29 vs 9.4.0.1.29 -> 尾段 1.29 一致
    assert s.checksum is not None
    assert s.checksum.hex8 == "deadbeef"
    assert s.warnings == ()
    assert s.bios_bin_bytes == 8 * 1024 * 1024
    assert s.ec_bin_bytes == 128 * 1024


def test_validate_ec_version_mismatch_warns(tmp_path: Path) -> None:
    """BIOS 内嵌 EC 0.1.29 vs EC 包 9.4.0.1.28 -> 软告警, 不阻断."""
    opts = synth.SynthOptions(ec_underscore_version="9_4_0_1_28")
    s = _validate(synth.synth_package(tmp_path / "pkg", opts))
    assert s.ec_consistent is False
    assert any("尾段不一致" in w for w in s.warnings)


def test_validate_bios_bin_too_small(tmp_path: Path) -> None:
    pkg = synth.synth_package(tmp_path / "pkg", synth.SynthOptions(bios_bin_bytes=4 * 1024 * 1024))
    with pytest.raises(ValidationError) as exc:
        _validate(pkg)
    assert "BIOS bin" in exc.value.what
    assert "8 MiB" in exc.value.what


@pytest.mark.parametrize("size", [100 * 1024, 63 * 1024, 1024 * 1024])
def test_validate_ec_bin_bad_size(tmp_path: Path, size: int) -> None:
    pkg = synth.synth_package(tmp_path / "pkg", synth.SynthOptions(ec_bin_bytes=size))
    with pytest.raises(ValidationError) as exc:
        _validate(pkg)
    assert "EC bin" in exc.value.what
    assert "允许集合" in exc.value.what


def test_validate_corrupt_ifu_efi(pkg: Path) -> None:
    (_ec_dir(pkg) / "ifu.efi").write_bytes(b"definitely not a pe file")
    with pytest.raises(ValidationError) as exc:
        _validate(pkg)
    assert "ifu.efi" in exc.value.what
    assert "PE/COFF" in exc.value.what


def test_validate_corrupt_afu_efi(pkg: Path) -> None:
    tools = _bios_dir(pkg) / "Tools"
    (tools / "AfuEfix64.efi").write_bytes(b"MZ" + b"\x00" * 10)  # MZ 有, PE 无
    with pytest.raises(ValidationError, match="AfuEfix64.efi"):
        _validate(pkg)


def test_validate_nflash_ref_broken(pkg: Path) -> None:
    tools = _bios_dir(pkg) / "Tools"
    (tools / "nFlash.nsh").write_text(
        "@echo -off\r\nfor %a in *bin\r\nendfor\r\n", encoding="ascii", newline=""
    )
    with pytest.raises(ValidationError) as exc:
        _validate(pkg)
    assert "nFlash.nsh" in exc.value.what
    assert "Tools" in exc.value.what


def test_validate_fec_ref_mismatch(pkg: Path) -> None:
    """换版本时只改了 bin 名忘改 FEC64.NSH -> 必须拦截."""
    ec = _ec_dir(pkg)
    opts = synth.SynthOptions()
    shutil.move(ec / opts.ec_bin_name, ec / "EC_TESTX1_V9_4_0_1_28F.bin")
    with pytest.raises(ValidationError) as exc:
        _validate(pkg)
    assert "FEC64.NSH" in exc.value.what
    assert "V9_4_0_1_28F" in exc.value.what


def test_validate_bios_bin_name_unparseable(pkg: Path) -> None:
    shutil.move(
        _bios_dir(pkg) / synth.SynthOptions().bios_bin_name,
        _bios_dir(pkg) / "firmware.bin",
    )
    with pytest.raises(ValidationError) as exc:
        _validate(pkg)
    assert "解析版本" in exc.value.what


def test_validate_model_dirname_mismatch_warns(pkg: Path) -> None:
    shutil.move(_bios_dir(pkg), pkg / "OTHER1_1.06_BIOS")
    s = _validate(pkg)
    assert s.model == "OTHER1"  # 以 BIOS 目录为准
    assert any("机型不一致" in w for w in s.warnings)


def test_validate_model_unparseable_dirs(pkg: Path) -> None:
    shutil.move(_bios_dir(pkg), pkg / "1.06_BIOS")
    shutil.move(_ec_dir(pkg), pkg / "1.29EC")
    with pytest.raises(ValidationError, match="机型名"):
        _validate(pkg)


def test_validate_checksum_name_mismatch_warns(pkg: Path) -> None:
    ec = _ec_dir(pkg)
    (ec / "ChecksumF.txt").write_text(
        "[EC_OTHER_V1_0F.bin] checksum : deadbeef\r\n", encoding="ascii", newline=""
    )
    s = _validate(pkg)
    assert any("ChecksumF.txt 记录的 bin 名" in w for w in s.warnings)


def test_validate_checksum_unparseable_warns(pkg: Path) -> None:
    (_ec_dir(pkg) / "ChecksumF.txt").write_text("garbage\r\n", encoding="ascii", newline="")
    s = _validate(pkg)
    assert s.checksum is None
    assert any("未能解析" in w for w in s.warnings)


def test_validate_no_checksum_ok(tmp_path: Path) -> None:
    pkg = synth.synth_package(tmp_path / "pkg", synth.SynthOptions(with_checksum=False))
    s = _validate(pkg)
    assert s.checksum is None
    assert s.warnings == ()


def _bios_dir(pkg: Path) -> Path:
    return pkg / synth.SynthOptions().bios_dir_name


def _ec_dir(pkg: Path) -> Path:
    return pkg / synth.SynthOptions().ec_dir_name
