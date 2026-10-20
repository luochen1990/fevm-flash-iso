# 职责边界: FAT 引导镜像构建 (truncate + mkfs.vfat + mcopy, 实测参数)。
# 命令语义 2026-10 实机验证, 不要改: FAT16; BIOS 盘 64MiB / EC 盘 8MiB;
# 每扇区簇数显式指定 (dosfstools 4.2 自动适配在 8MiB 上失败, 见 BuildSpec)。

"""FAT16 引导镜像构建。"""

from pathlib import Path

from .cmd import run_ok
from .model import BuildSpec


def build_fat_image(image: Path, stage_dir: Path, spec: BuildSpec) -> None:
    """把 stage_dir 的各顶层条目打包进 image (FAT16, 卷标见 spec).

    契约: image 路径在 isoroot 源目录树内 (xorriso 的 -e 要求镜像在源
    目录树内 —— 实测踩坑), 由调用方保证。
    """
    run_ok(["truncate", "-s", f"{spec.fat_size_mib}M", image])
    run_ok([
        "mkfs.vfat", "-F", "16",
        "-s", str(spec.fat_sectors_per_cluster),
        "-n", spec.fat_label,
        image,
    ])
    for entry in sorted(stage_dir.iterdir()):
        run_ok(["mcopy", "-i", image, "-s", entry, "::"])
