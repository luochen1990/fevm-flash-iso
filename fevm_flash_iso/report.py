# 职责边界: 人机界面 (纯输出, 无业务逻辑)。解析摘要表、每个 ISO 的内容
# 清单、下一步操作提示 —— 所有用户可见文本集中于此, 便于审阅与翻译。

"""终端报告: 摘要表 / 产物清单 / 下一步操作提示。"""

import sys
from collections.abc import Sequence
from pathlib import Path

from .model import FlashTarget
from .validate import FirmwareSummary

_WIDTH = 66
_KEY_WIDTH = 18


def _rule(title: str = "") -> None:
    label = f" {title} " if title else ""
    pad = _WIDTH - _display_width(label)
    print(f"{'=' * (pad // 2)}{label}{'=' * (pad - pad // 2)}")


def _display_width(s: str) -> int:
    """终端显示宽度 (CJK 字符按 2 列计)."""
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in s)


def _kv(key: str, value: str) -> None:
    pad = " " * max(_KEY_WIDTH - _display_width(key), 1)
    print(f"  {key}{pad}: {value}")


def print_summary(summary: FirmwareSummary) -> None:
    """打印机型/版本摘要表 (校验清单 #6 的醒目展示 + warnings)."""
    _rule("固件包解析摘要")
    _kv("机型", summary.model)
    _kv(
        "BIOS 版本",
        f"{summary.bios_bin.bios_display} (bin {summary.bios_bin_bytes / 1048576:.1f} MiB)",
    )
    _kv("BIOS 内嵌 EC 版本", summary.bios_bin.embedded_ec_display)
    _kv(
        "EC 包版本",
        f"{summary.ec_bin.display} (bin {summary.ec_bin_bytes / 1024:.0f} KiB)",
    )
    if summary.ec_consistent:
        _kv("EC 版本一致性", "OK (release 尾段一致)")
    else:
        _kv("EC 版本一致性", "不一致 (见下方警告)")
    if summary.checksum is not None:
        _kv(
            "ChecksumF",
            f"[{summary.checksum.bin_name}] checksum : {summary.checksum.hex8}"
            " (ITE 私有算法未知, 供人工比对)",
        )
    if summary.warnings:
        print("  警告:")
        for w in summary.warnings:
            print(f"    - {w}")
    _rule()


def print_product(
    index: int, total: int, target: FlashTarget, iso: Path, listing: Sequence[str]
) -> None:
    """打印单个 ISO 产物与其 FAT 镜像内容清单."""
    size_mib = iso.stat().st_size / 1048576
    print(f"产物 {index}/{total} [{target.value}]: {iso.name} ({size_mib:.1f} MiB)")
    print(f"  路径: {iso}")
    print("  FAT 镜像内容:")
    for line in listing:
        print(f"    {line}")
    print("  自检: xorriso -indev OK, El Torito EFI 引导记录 OK, FAT 关键路径 OK")


def print_next_steps(iso_names: Sequence[str]) -> None:
    """打印下一步操作提示 (Ventoy -> F7 -> 5 秒自动刷 -> 按 y / 断电 10 秒)."""
    _rule("下一步操作")
    print("  1. 把生成的 ISO 拷入 Ventoy U 盘:")
    for name in iso_names:
        print(f"     - {name}")
    print("  2. 目标机开机按 F7 进入启动菜单, 选择对应 ISO")
    print("  3. UEFI Shell 启动后 5 秒倒计时结束即自动开始刷写")
    print("  4. BIOS 盘: 刷写工具要求确认时按 y")
    print("  5. EC 盘: 刷写完成后自动关机; 必须断电 (拔电源) 等 10 秒再通电")
    _rule()


def print_error(message: str) -> None:
    """以统一格式输出错误到 stderr."""
    print(f"错误: {message}", file=sys.stderr)


def print_stage_note(stage_root: Path) -> None:
    """--keep-stage 时提示中间目录位置."""
    print(f"stage 中间目录已保留: {stage_root}")
