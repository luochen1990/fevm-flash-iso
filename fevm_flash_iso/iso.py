# 职责边界: 最终 ISO 组装与产物自检 (校验清单 #8)。xorriso 参数实测验证
# (Ventoy 引导场景), 不要改语义: -eltorito-alt-boot -e efi.img -no-emul-boot
# + -append_partition 2 0xEF efi.img。自检对象是**成品 ISO 的内嵌副本**
# (m-1): 抽回 /efi.img 与源镜像哈希比对 + 对内嵌副本跑 mdir 路径检查;
# El Torito 判定解析 Platform Id 行 (EFI/UEFI), 不靠子串碰运气。发布是
# 原子的: 调用方先构建到 <名>.iso.tmp, 本模块 verify_iso 通过后由调用方
# os.replace 到最终名 —— 校验失败绝不留下以正式名示人的坏 ISO。

"""ISO 组装 (xorriso -as mkisofs) 与产物自检。"""

import hashlib
import re
from collections.abc import Sequence
from pathlib import Path

from .cmd import run_ok
from .errors import BuildError
from .model import EFI_IMG_NAME

# xorriso -report_el_torito plain 输出中引导项行的 Platform Id 列:
# "El Torito boot img :   1  UEFI  y   none  0x0000 ..."
_ELTORITO_BOOT_IMG_RE = re.compile(r"El Torito boot img\s*:\s*\d+\s+(EFI|UEFI)\s")
_ELTORITO_IMG_PATH_RE = re.compile(
    r"El Torito img path\s*:\s*\d+\s+/" + re.escape(EFI_IMG_NAME) + r"(?=\s|$)"
)


def build_iso(isoroot: Path, out_iso: Path, volid: str) -> None:
    """把 isoroot/ 目录树打成可引导 ISO.

    契约: 以 isoroot 为工作目录执行, efi.img 用裸相对路径同时喂给 -e
    (指向源目录树内) 与 -append_partition (指向磁盘 cwd) —— 这要求镜像
    文件就在 isoroot 里, 由调用方保证。out_iso 通常是 <名>.iso.tmp,
    由调用方在自检通过后原子改名。
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


def _has_efi_eltorito(report_text: str) -> bool:
    """纯解析: 判定 xorriso El Torito 报告里是否存在 EFI/UEFI 引导项
    且引导镜像路径为 /efi.img (Platform Id 行解析, 不做裸子串匹配)."""
    return (
        _ELTORITO_BOOT_IMG_RE.search(report_text) is not None
        and _ELTORITO_IMG_PATH_RE.search(report_text) is not None
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_iso(
    iso: Path,
    source_fat_image: Path,
    expected_paths: Sequence[str],
    workdir: Path,
) -> None:
    """产物自检 (对象 = 成品 ISO 的内嵌副本):
    1. xorriso -indev 可读 + El Torito Platform Id 为 EFI/UEFI + 引导镜像 /efi.img;
    2. -osirrox 抽回内嵌 /efi.img, 与源 FAT 镜像 SHA-256 比对;
    3. 对内嵌副本逐路径 mdir 检查关键布局。
    """
    report = run_ok(["xorriso", "-indev", iso, "-report_el_torito", "plain"])
    text = f"{report.stdout}\n{report.stderr}"
    if not _has_efi_eltorito(text):
        raise BuildError(
            f"自检失败: {iso.name} 中未找到 EFI/UEFI El Torito 引导记录 (/{EFI_IMG_NAME})"
        )

    extracted = workdir / "verify-extracted.img"
    run_ok([
        "xorriso", "-osirrox", "on", "-indev", iso,
        "-extract", f"/{EFI_IMG_NAME}", extracted,
    ])
    if _sha256(extracted) != _sha256(source_fat_image):
        raise BuildError(
            f"自检失败: {iso.name} 内嵌 {EFI_IMG_NAME} 与源 FAT 镜像哈希不一致 (写入损坏)",
        )
    for rel in expected_paths:
        run_ok(["mdir", "-i", extracted, f"::/{rel}"])


def list_fat_tree(fat_image: Path) -> tuple[str, ...]:
    """FAT 镜像递归清单 (mdir -/ -b), 供报告层展示 ISO 内容."""
    proc = run_ok(["mdir", "-/", "-b", "-i", fat_image, "::"])
    lines = [ln.removeprefix("::/").rstrip() for ln in proc.stdout.splitlines()]
    return tuple(ln for ln in lines if ln)
