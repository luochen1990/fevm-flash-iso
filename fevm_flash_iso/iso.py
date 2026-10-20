# 职责边界: 最终 ISO 组装与产物自检 (校验清单 #8)。xorriso 参数实测验证
# (Ventoy 引导场景), 不要改语义: -eltorito-alt-boot -e efi.img -no-emul-boot
# + -append_partition 2 0xEF efi.img。自检 = xorriso -indev 可读 + El Torito
# EFI 引导记录存在 + mdir 检查 FAT 镜像关键路径齐全, 任一不过即 BuildError。

"""ISO 组装 (xorriso -as mkisofs) 与产物自检。"""

from collections.abc import Sequence
from pathlib import Path

from .cmd import run_ok
from .errors import BuildError
from .model import EFI_IMG_NAME


def build_iso(isoroot: Path, out_iso: Path, volid: str) -> None:
    """把 isoroot/ 目录树打成可引导 ISO.

    契约: 以 isoroot 为工作目录执行, efi.img 用裸相对路径同时喂给 -e
    (指向源目录树内) 与 -append_partition (指向磁盘 cwd) —— 这要求镜像
    文件就在 isoroot 里, 由调用方保证。
    """
    run_ok([
        "xorriso", "-as", "mkisofs",
        "-quiet",
        "-volid", volid,
        "-J", "-joliet-long",
        "-eltorito-alt-boot",
        "-e", EFI_IMG_NAME,
        "-no-emul-boot",
        "-append_partition", "2", "0xEF", EFI_IMG_NAME,
        "-o", out_iso.resolve(),
        ".",
    ], cwd=isoroot)


def verify_iso(iso: Path, fat_image: Path, expected_paths: Sequence[str]) -> None:
    """产物自检: ISO 可读 + El Torito EFI 引导记录 + FAT 镜像关键路径."""
    report = run_ok(["xorriso", "-indev", iso, "-report_el_torito", "plain"])
    text = f"{report.stdout}\n{report.stderr}"
    if "UEFI" not in text or f"/{EFI_IMG_NAME}" not in text:
        raise BuildError(
            f"自检失败: {iso.name} 中未找到 El Torito EFI 引导记录 (/efi.img)",
        )
    for rel in expected_paths:
        run_ok(["mdir", "-i", fat_image, f"::/{rel}"])


def list_fat_tree(fat_image: Path) -> tuple[str, ...]:
    """FAT 镜像递归清单 (mdir -/ -b), 供报告层展示 ISO 内容."""
    proc = run_ok(["mdir", "-/", "-b", "-i", fat_image, "::"])
    lines = [ln.removeprefix("::/").rstrip() for ln in proc.stdout.splitlines()]
    return tuple(ln for ln in lines if ln)
