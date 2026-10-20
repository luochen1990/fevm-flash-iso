# 职责边界: stage 目录组装 (纯文件复制, 不调外部命令)。按 FAT 镜像布局
# 把 "Shell + startup.nsh + README + 厂商 payload" 复制成源树, 并同步给
# 出期望出现在 FAT 镜像内的关键路径清单 (供产物自检 #8 用)。布局常量与
# startup.nsh 探测路径同源 (model.BUILD_SPECS), 改布局只改一处。

"""stage 目录组装: 源树构建与期望路径清单。"""

import shutil
from dataclasses import dataclass
from pathlib import Path

from .model import (
    BOOT_EFI_REL,
    README_NAME,
    STARTUP_NSH_NAME,
    BuildSpec,
    FlashTarget,
)
from .validate import FirmwareSummary


@dataclass(frozen=True)
class CopyAction:
    """一条 staging 动作: 目标相对路径 + 来源 (文件或内联文本)."""

    dest_rel: str
    src_file: Path | None = None
    text: str | None = None


def stage_actions(spec: BuildSpec, summary: FirmwareSummary, shell_efi: Path,
                  startup_nsh: str, readme: str) -> tuple[CopyAction, ...]:
    """生成某目标的全部 staging 动作 (声明式, assemble 逐条执行)."""
    actions: list[CopyAction] = [
        CopyAction(dest_rel=BOOT_EFI_REL, src_file=shell_efi),
        CopyAction(dest_rel=STARTUP_NSH_NAME, text=startup_nsh),
        CopyAction(dest_rel=README_NAME, text=readme),
    ]
    layout = summary.layout
    # payload_entry (如 "Tools\nFlash.nsh") 是布局 SSOT: NSH 探测用反斜杠原样,
    # staging 路径转成正斜杠 —— 改布局只改 model.BUILD_SPECS 一处
    entry_rel = spec.payload_entry.replace("\\", "/")
    if spec.target is FlashTarget.BIOS:
        actions += [
            CopyAction(dest_rel=f"{spec.payload_dir}/{layout.bios.bin_path.name}",
                       src_file=layout.bios.bin_path),
            CopyAction(dest_rel=f"{spec.payload_dir}/Tools/AfuEfix64.efi",
                       src_file=layout.bios.afu_efi),
            CopyAction(dest_rel=f"{spec.payload_dir}/{entry_rel}",
                       src_file=layout.bios.nflash_nsh),
        ]
    else:
        actions += [
            CopyAction(dest_rel=f"{spec.payload_dir}/{layout.ec.bin_path.name}",
                       src_file=layout.ec.bin_path),
            CopyAction(dest_rel=f"{spec.payload_dir}/ifu.efi", src_file=layout.ec.ifu_efi),
            CopyAction(dest_rel=f"{spec.payload_dir}/{entry_rel}",
                       src_file=layout.ec.fec_nsh),
        ]
        if layout.ec.uiset_ini is not None:
            actions.append(
                CopyAction(dest_rel=f"{spec.payload_dir}/uiset.ini", src_file=layout.ec.uiset_ini)
            )
        # ChecksumF.txt 随盘分发: "供人工比对"的信息跟着 ISO 走 (n-5)
        if layout.ec.checksum_txt is not None:
            actions.append(
                CopyAction(
                    dest_rel=f"{spec.payload_dir}/{layout.ec.checksum_txt.name}",
                    src_file=layout.ec.checksum_txt,
                )
            )
    return tuple(actions)


def assemble_stage(stage_dir: Path, actions: tuple[CopyAction, ...]) -> None:
    """把动作落盘到 stage_dir (已存在则要求为空或由调用方清理)."""
    for action in actions:
        dest = stage_dir / action.dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if action.src_file is not None:
            shutil.copy2(action.src_file, dest)
        elif action.text is not None:
            dest.write_text(action.text, encoding="ascii", newline="")
        else:  # pragma: no cover -- dataclass 构造约束保证二选一
            raise ValueError(f"空的 staging 动作: {action.dest_rel}")


def expected_image_paths(actions: tuple[CopyAction, ...]) -> tuple[str, ...]:
    """产物自检 #8 用: FAT 镜像内必须存在的全部路径 (与动作一一对应)."""
    return tuple(a.dest_rel for a in actions)
