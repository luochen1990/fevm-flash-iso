# 职责边界: startup.nsh / README.txt 模板测试 —— 重点覆盖 EDK2 Shell 的
# 已知坑 (echo flag / 探测循环 / CRLF) 与人机操作要点文案。

"""texts (startup.nsh / README.txt) 测试。"""

import pytest

from fevm_flash_iso.model import BUILD_SPECS, FlashTarget
from fevm_flash_iso.texts import (
    bios_banner,
    bios_readme_extra_steps,
    ec_banner,
    ec_readme_extra_steps,
    render_readme,
    render_startup_nsh,
)

_BAD_ECHO_START = "-=/"


def _startup(target: FlashTarget) -> str:
    spec = BUILD_SPECS[target]
    if target is FlashTarget.BIOS:
        banner = bios_banner("TESTX1", "V1.06", "V0.1.29")
    else:
        banner = ec_banner("TESTX1", "V9.4.0.1.29F")
    return render_startup_nsh(spec, banner)


@pytest.mark.parametrize("target", list(FlashTarget))
def test_startup_nsh_skeleton(target: FlashTarget) -> None:
    """EDK2 语法骨架: 倒计时 + 探测循环 + 目标路径唯一命中 (无 goto)."""
    spec = BUILD_SPECS[target]
    text = _startup(target)
    assert text.startswith("@echo -off")
    assert "stall 5000000" in text  # 5 秒倒计时
    assert "for %a run (0 9)" in text  # fs 设备号探测循环
    assert "endfor" in text
    assert f"if exist fs%a:\\{spec.probe_path} then" in text
    assert f"    cd {spec.payload_dir}" in text
    assert f"    {spec.payload_entry}" in text
    assert "goto" not in text  # 坑: 跨块 goto 语义不稳


@pytest.mark.parametrize("target", list(FlashTarget))
def test_startup_nsh_crlf(target: FlashTarget) -> None:
    """与厂商脚本一致, 行尾 CRLF."""
    text = _startup(target)
    assert "\r\n" in text
    assert text.endswith("\r\n")


@pytest.mark.parametrize("target", list(FlashTarget))
def test_startup_nsh_no_echo_flag_trap(target: FlashTarget) -> None:
    """坑 (实测踩过): echo 内容以 -, =, / 开头会报 'echo: Unknown flag'."""
    for line in _startup(target).split("\r\n"):
        stripped = line.removeprefix("echo ")
        if stripped != line and stripped.strip():
            assert stripped.lstrip()[0] not in _BAD_ECHO_START, f"违规 echo 行: {line!r}"


def test_bios_banner_mentions_confirmation() -> None:
    banner = bios_banner("TESTX1", "V1.06", "V0.1.29")
    assert any("y" in line for line in banner)
    assert any("BIOS" in line for line in banner)


def test_ec_banner_mentions_power_cycle() -> None:
    banner = ec_banner("TESTX1", "V9.4.0.1.29F")
    assert any("10 seconds" in line for line in banner)
    assert any("powers off" in line for line in banner)


def test_bios_readme_content() -> None:
    spec = BUILD_SPECS[FlashTarget.BIOS]
    text = render_readme(
        spec, "TESTX1", "BIOS V1.06 (embedded EC V0.1.29)", bios_readme_extra_steps()
    )
    assert "Ventoy" in text
    assert "F7" in text
    assert "press y" in text
    assert spec.payload_dir in text


def test_ec_readme_content() -> None:
    spec = BUILD_SPECS[FlashTarget.EC]
    text = render_readme(spec, "TESTX1", "EC V9.4.0.1.29F (ITE IT5570E)", ec_readme_extra_steps())
    assert "Ventoy" in text
    assert "F7" in text
    assert "10 seconds" in text
    assert "powers off" in text
