# 职责边界: filenames 纯函数解析测试 (文件名规约 / 版本提取 / checksum 行)。

"""filenames 解析测试。"""

import pytest

from fevm_flash_iso.filenames import (
    ec_versions_consistent,
    parse_bios_bin_name,
    parse_checksum_text,
    parse_ec_bin_name,
    parse_model_dirname,
    release_tail,
)

# 与实测 FEVM 命名规约同构的合成样例 (非真实文件名)
BIOS_NAME = (
    "TESTX1_FP11_STXH_TEST_S112_V1.06_M0TEST_8000_1_12_EC_V0.1.29_20260720.bin"
)
EC_NAME = "EC_FEVM_V9_4_0_1_29F.bin"


def test_parse_bios_bin_name_full_shape() -> None:
    r = parse_bios_bin_name(BIOS_NAME)
    assert r is not None
    assert r.bios_version == "1.06"
    assert r.embedded_ec_version == "0.1.29"
    assert r.bios_display == "V1.06"
    assert r.embedded_ec_display == "V0.1.29"


@pytest.mark.parametrize("name", ["firmware.bin", "A_V1.06_only.bin", "A_EC_V0.1.29_only.bin"])
def test_parse_bios_bin_name_missing_fields(name: str) -> None:
    assert parse_bios_bin_name(name) is None


def test_parse_bios_bin_name_embedded_no_trailing_dot() -> None:
    """m-4 回归: EC 版本不得吞尾点 (曾导致假 "版本不一致" 警告)."""
    r = parse_bios_bin_name("A_V1.06_EC_V0.1.29.bin")
    assert r is not None
    assert r.bios_version == "1.06"
    assert r.embedded_ec_version == "0.1.29"
    assert not r.embedded_ec_version.endswith(".")


def test_parse_bios_bin_name_multiple_version_candidates_raises() -> None:
    """n-4: 多个互不相同的 BIOS 版本字段 => 硬失败, 不静默取第一个."""
    with pytest.raises(ValueError, match="多个版本候选"):
        parse_bios_bin_name("A_V1.06_B_V2.00_EC_V0.1.29.bin")


def test_parse_bios_bin_name_repeated_same_version_ok() -> None:
    """重复出现同一版本值不算歧义."""
    r = parse_bios_bin_name("A_V1.06_B_V1.06_EC_V0.1.29.bin")
    assert r is not None
    assert r.bios_version == "1.06"


def test_parse_ec_bin_name_with_f_suffix() -> None:
    r = parse_ec_bin_name(EC_NAME)
    assert r is not None
    assert r.project == "FEVM"
    assert r.version == "9.4.0.1.29"
    assert r.f_suffix is True
    assert r.display == "V9.4.0.1.29F"


def test_parse_ec_bin_name_without_f_suffix() -> None:
    r = parse_ec_bin_name("EC_FEVM_V9_4_0_1_29.bin")
    assert r is not None
    assert r.f_suffix is False
    assert r.display == "V9.4.0.1.29"


@pytest.mark.parametrize("name", ["EC_FEVM_V9.bin", "random.bin", "EC_FEVM_VX_Y.bin"])
def test_parse_ec_bin_name_invalid(name: str) -> None:
    assert parse_ec_bin_name(name) is None


@pytest.mark.parametrize(
    ("dirname", "model"),
    [("TESTX1_1.06_BIOS", "TESTX1"), ("TESTX1_1.29EC", "TESTX1"), ("FAEX1_BIOS", "FAEX1")],
)
def test_parse_model_dirname_ok(dirname: str, model: str) -> None:
    assert parse_model_dirname(dirname) == model


@pytest.mark.parametrize("dirname", ["_leading", "1numeric_start", "with space_x"])
def test_parse_model_dirname_invalid(dirname: str) -> None:
    assert parse_model_dirname(dirname) is None


@pytest.mark.parametrize(
    ("version", "tail"),
    [("0.1.29", "1.29"), ("9.4.0.1.29", "1.29"), ("1.28", "1.28"), ("7", "7")],
)
def test_release_tail(version: str, tail: str) -> None:
    assert release_tail(version) == tail


def test_ec_versions_consistent_real_shape() -> None:
    """实测形态: BIOS 内嵌 EC_V0.1.29 与 EC 包 9_4_0_1_29F 尾段一致."""
    assert ec_versions_consistent("0.1.29", "9.4.0.1.29") is True
    assert ec_versions_consistent("0.1.28", "9.4.0.1.29") is False


def test_parse_checksum_text_ok() -> None:
    text = (
        "\r\n"
        "---------------------------------------------------------------------- \r\n"
        "FU.EXE - Firmware Utility     Version : 1.5.0    ITE Dino 2011.09 \r\n"
        "---------------------------------------------------------------------- \r\n"
        f"[{EC_NAME}] checksum : AB1C2D3F\r\n"
    )
    entry = parse_checksum_text(text)
    assert entry is not None
    assert entry.bin_name == EC_NAME
    assert entry.hex8 == "ab1c2d3f"  # 统一小写


def test_parse_checksum_text_garbage() -> None:
    assert parse_checksum_text("no checksum here\r\n") is None
    assert parse_checksum_text("[x.bin] checksum : zzz") is None
