# 职责边界: FAT 引导镜像与最终 ISO 内的文本生成 (纯函数): startup.nsh
# 与 README.txt。所有 EDK2 UEFI Shell 2.2 的已知坑在这里集中规避:
#
# 坑 1: echo 的内容绝不能以 '-', '=', '/' 等开头 (EDK2 echo 把首 token
#       当 flag 解析, 报 "echo: Unknown flag") —— 提示文本一律字母数字
#       开头, 分隔线用 'xxx...' 字母串。
# 坑 2: 不用 goto 跳出 for 循环 (EDK2 Shell 跨块 goto 语义不稳), 采用
#       「目标路径唯一命中」的自然结构。
# 坑 3: fs 设备号不固定 (实测 Ventoy 场景 ISO 挂在 FS1), 必须用
#       fs0..fs9 探测循环。
# 坑 4: 行尾用 CRLF, 与厂商脚本一致。
# 坑 5: 循环变量只能用单个 ASCII 字母 (EDK2 For.c 强制校验), 且必须与
#       厂商脚本错开 —— 厂商 nFlash.nsh 用 %a, 这里用 %z (m-9: 同名会
#       被内层脚本覆盖, 多字符名则直接 "Invalid variable name" 拒绝)。
#
# 允许的命令集: @echo -off / echo / stall / for %z run (0 9) / endfor /
# if exist ... then / endif / fs%z: / cd / 厂商脚本调用。

"""startup.nsh 与 README.txt 模板生成 (纯函数, CRLF)。"""

from collections.abc import Sequence

from .model import BOOT_EFI_REL, README_NAME, STARTUP_NSH_NAME, BuildSpec

_SEPARATOR = "x" * 68
_LOOP_VAR = "z"


def render_startup_nsh(
    spec: BuildSpec,
    banner_lines: Sequence[str],
) -> str:
    """渲染 startup.nsh: 横幅 -> 5 秒倒计时 -> fs0..fs9 探测 -> 调厂商脚本.

    契约: banner_lines 中每行都会原样输出为 echo 行, 调用方必须保证不以
    '-', '=', '/' 开头 (见坑 1); 本函数不做转义 —— 模板内容全部静态可控。
    """
    lines: list[str] = [
        "@echo -off",
        "echo",
        f"echo {_SEPARATOR}",
        *(f"echo {line}" for line in banner_lines),
        f"echo {_SEPARATOR}",
        "echo",
        "echo Auto start in 5 seconds ...",
        "stall 5000000",
        "echo Searching flash payload on fs0 .. fs9 ...",
        f"for %{_LOOP_VAR} run (0 9)",
        f"  if exist fs%{_LOOP_VAR}:\\{spec.probe_path} then",
        f"    echo Found payload on fs%{_LOOP_VAR}. Launching vendor flash script.",
        f"    fs%{_LOOP_VAR}:",
        f"    cd {spec.payload_dir}",
        f"    {spec.payload_entry}",
        "    echo Vendor flash script returned. Review its output above.",
        "  endif",
        "endfor",
        "echo",
        "echo Payload NOT found on fs0 .. fs9. Boot device may differ.",
        "echo Reboot this machine and boot the ISO again via Ventoy.",
    ]
    return "\r\n".join(lines) + "\r\n"


def bios_banner(model: str, bios_version: str, embedded_ec_version: str) -> tuple[str, ...]:
    """BIOS 盘横幅 (含人机操作要点: 按 y 确认)."""
    return (
        f"FEVM {model} BIOS flash disk",
        f"BIOS {bios_version} (embedded EC {embedded_ec_version})",
        "WARNING: this disk reprograms the BIOS. Keep AC power connected.",
        "Confirm with y when the flash tool asks.",
    )


def ec_banner(model: str, ec_version: str) -> tuple[str, ...]:
    """EC 盘横幅 (含人机操作要点: 自动关机 + 断电 10 秒)."""
    return (
        f"FEVM {model} EC flash disk",
        f"EC {ec_version} (ITE IT5570E via ifu.efi)",
        "After a successful flash the machine powers off automatically.",
        "Unplug AC power, wait 10 seconds, then power on again.",
    )


def render_readme(
    spec: BuildSpec,
    model: str,
    firmware_line: str,
    extra_steps: Sequence[str],
) -> str:
    """渲染 ISO 内 README.txt (同时落在 FAT 镜像与 ISO 根目录两处)."""
    steps = [
        "How to use",
        "----------",
        "1. Copy this ISO file onto a Ventoy USB stick.",
        "2. On the target FEVM machine, power on and press F7 to open the",
        "   boot menu, then select this ISO.",
        "3. The UEFI Shell starts and flashes automatically after a",
        "   5 second countdown.",
        *extra_steps,
    ]
    layout = [
        "Layout",
        "------",
        f"{BOOT_EFI_REL:<21} edk2 UEFI Shell 2.2",
        f"{STARTUP_NSH_NAME:<21} auto start script (payload finder)",
        f"{README_NAME:<21} this file",
        f"{spec.payload_dir + '/':<21} vendor flash payload",
    ]
    body = "\n".join(
        [
            f"FEVM {model} flash disk ({spec.target.value})",
            "=" * 40,
            "",
            f"Firmware   : {firmware_line}",
            "Built by   : fevm-flash-iso (no-Windows flash pipeline)",
            "",
            *steps,
            "",
            *layout,
            "",
        ]
    )
    return body + "\n"


def bios_readme_extra_steps() -> tuple[str, ...]:
    return (
        "4. BIOS disk: when the flash tool asks for confirmation press y.",
        "5. Let the tool finish, then reboot when it tells you to.",
    )


def ec_readme_extra_steps() -> tuple[str, ...]:
    return (
        "4. EC disk: the machine powers off automatically after the flash.",
        "5. Unplug AC power, wait at least 10 seconds, then power on again.",
    )
