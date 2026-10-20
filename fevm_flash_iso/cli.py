# 职责边界: CLI 入口与管线编排。集中式预处理: 参数解析、路径规范化、
# 默认值收敛全部发生在 parse_args (核心逻辑拿到的都是合规的绝对路径);
# 之后按 校验 -> 解析 -> 构建 -> 自检 -> 报告 的顺序编排, 任何一步失败
# 即终止 (fail fast)。产物发布是原子的 (M-1): 先写 <名>.iso.tmp, 自检
# (含内嵌副本哈希比对) 通过后 os.replace 到最终名; 任一构建失败时清理
# 本次运行已写出的全部 .iso/.tmp 残留。退出码: 0 成功, 2 输入/环境校验
# 失败, 3 构建或自检失败 (含未预期的 I/O 错误)。

"""CLI: fevm-flash-iso <包根目录> [-o 输出目录] [--shell-efi PATH]
     [--bios-dir PATH] [--ec-dir PATH] [--keep-stage]
"""

import argparse
import os
import shutil
import sys
import tempfile
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from . import report
from .cmd import require_tools
from .discover import discover
from .errors import BuildError, ValidationError
from .fatimg import build_fat_image
from .iso import build_iso, list_fat_tree, verify_iso
from .model import (
    BUILD_SPECS,
    EFI_IMG_NAME,
    README_NAME,
    BuildSpec,
    FlashTarget,
)
from .shell import resolve_shell_efi
from .stage import assemble_stage, expected_image_paths, stage_actions
from .texts import (
    bios_banner,
    bios_readme_extra_steps,
    ec_banner,
    ec_readme_extra_steps,
    render_readme,
    render_startup_nsh,
)
from .validate import FirmwareSummary, validate


@dataclass(frozen=True)
class CliArgs:
    """解析后的参数 (全部规范化: 绝对路径, 默认值已收敛)."""

    package_root: Path
    out_dir: Path
    shell_efi: Path | None
    keep_stage: bool
    bios_dir: Path | None
    ec_dir: Path | None


@dataclass(frozen=True)
class Product:
    """一个成功构建并自检通过的刷写 ISO."""

    target: FlashTarget
    iso: Path
    listing: tuple[str, ...]


def tmp_name_for(final_name: str) -> str:
    """原子发布的临时文件名: <产物名>.iso -> <产物名>.iso.tmp."""
    return f"{final_name}.tmp"


def parse_args(argv: Sequence[str]) -> CliArgs:
    """argv -> CliArgs (集中式预处理: 路径 resolve, 输出目录默认 <包根>/dist)."""
    parser = argparse.ArgumentParser(
        prog="fevm-flash-iso",
        description="校验 FEVM 固件包并构建 UEFI Shell 全自动刷写 ISO (BIOS 盘 / EC 盘)",
    )
    parser.add_argument("package_root", type=Path, help="FEVM 固件包根目录")
    parser.add_argument("-o", "--out-dir", type=Path, default=None,
                        help="输出目录 (默认 <包根>/dist)")
    parser.add_argument("--shell-efi", type=Path, default=None,
                        help="覆盖内置 UEFI Shell (edk2 Shell 2.2 x64 EFI 文件)")
    parser.add_argument("--bios-dir", type=Path, default=None,
                        help="显式指定 BIOS 目录 (跳过自动识别)")
    parser.add_argument("--ec-dir", type=Path, default=None,
                        help="显式指定 EC 目录 (跳过自动识别)")
    parser.add_argument("--keep-stage", action="store_true",
                        help="保留 stage/isoroot 中间目录 (默认用临时目录并清理)")
    ns = parser.parse_args(argv)
    root = ns.package_root.resolve()
    out_dir = ns.out_dir.resolve() if ns.out_dir is not None else root / "dist"
    return CliArgs(
        package_root=root,
        out_dir=out_dir,
        shell_efi=ns.shell_efi.resolve() if ns.shell_efi is not None else None,
        keep_stage=ns.keep_stage,
        bios_dir=ns.bios_dir.resolve() if ns.bios_dir is not None else None,
        ec_dir=ns.ec_dir.resolve() if ns.ec_dir is not None else None,
    )


def iso_product_name(spec: BuildSpec, summary: FirmwareSummary) -> str:
    """产物命名: <机型>_FLASH_<BIOS|EC>_V<版本>.iso."""
    if spec.target is FlashTarget.BIOS:
        version = summary.bios_bin.bios_display
    else:
        version = summary.ec_bin.display
    return f"{summary.model}_FLASH_{spec.target.value}_{version}.iso"


def _banner_and_steps(
    spec: BuildSpec, summary: FirmwareSummary,
) -> tuple[tuple[str, ...], str, tuple[str, ...]]:
    """该目标的横幅行 / 固件行 / README 附加步骤."""
    if spec.target is FlashTarget.BIOS:
        return (
            bios_banner(summary.model, summary.bios_bin.bios_display,
                        summary.bios_bin.embedded_ec_display),
            f"BIOS {summary.bios_bin.bios_display} "
            f"(embedded EC {summary.bios_bin.embedded_ec_display})",
            bios_readme_extra_steps(),
        )
    return (
        ec_banner(summary.model, summary.ec_bin.display),
        f"EC {summary.ec_bin.display} (ITE IT5570E)",
        ec_readme_extra_steps(),
    )


def _stage_workdir(stack: ExitStack, args: CliArgs, target: FlashTarget) -> Path:
    """stage 工作目录: --keep-stage 时落在 out_dir/stage/<target>/ 并保留,
    否则用系统临时目录并随 stack 退出自动清理."""
    if args.keep_stage:
        path = args.out_dir / "stage" / target.value.lower()
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)
        return path
    tmp = tempfile.TemporaryDirectory(prefix=f"fevm-{target.value.lower()}-")
    stack.callback(tmp.cleanup)
    return Path(tmp.name)


def build_product(
    spec: BuildSpec,
    summary: FirmwareSummary,
    shell_efi: Path,
    args: CliArgs,
) -> Product:
    """构建单个刷写 ISO: stage -> FAT 镜像 -> isoroot -> xorriso(临时名)
    -> 自检(内嵌副本) -> 原子发布 (os.replace 到最终名)."""
    banner, firmware_line, steps = _banner_and_steps(spec, summary)
    readme = render_readme(spec, summary.model, firmware_line, steps)
    actions = stage_actions(
        spec, summary, shell_efi,
        startup_nsh=render_startup_nsh(spec, banner),
        readme=readme,
    )
    with ExitStack() as stack:
        workdir = _stage_workdir(stack, args, spec.target)
        stage_dir = workdir / "stage"
        isoroot = workdir / "isoroot"
        stage_dir.mkdir()
        isoroot.mkdir()
        assemble_stage(stage_dir, actions)

        fat_image = isoroot / EFI_IMG_NAME
        build_fat_image(fat_image, stage_dir, spec)
        (isoroot / README_NAME).write_text(readme, encoding="ascii", newline="")

        out_iso = args.out_dir / iso_product_name(spec, summary)
        tmp_iso = args.out_dir / tmp_name_for(out_iso.name)
        build_iso(isoroot, tmp_iso, spec.iso_volid)
        verify_iso(tmp_iso, fat_image, expected_image_paths(actions), workdir)
        os.replace(tmp_iso, out_iso)
        listing = list_fat_tree(fat_image)
    return Product(target=spec.target, iso=out_iso, listing=listing)


def _remove_partial_products(out_dir: Path, product_names: Sequence[str]) -> tuple[Path, ...]:
    """原子发布兜底: 删除本次运行可能已写出的全部 .iso / .iso.tmp 残留,
    返回实际删除的路径 (供报告). 预先存在的旧产物不在清理范围."""
    removed: list[Path] = []
    for name in product_names:
        for candidate in (out_dir / name, out_dir / tmp_name_for(name)):
            if candidate.is_file():
                candidate.unlink()
                removed.append(candidate)
    return tuple(removed)


def _abort_build(args: CliArgs, product_names: Sequence[str], message: str) -> int:
    """构建失败统一收尾 (退出码 3): 报错 + 兜底清理本次已写出的产物."""
    report.print_error(message)
    if args.out_dir.is_dir():
        report.print_discarded_products(_remove_partial_products(args.out_dir, product_names))
    return 3


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口: 返回进程退出码 (0/2/3, 见模块 docstring)."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    product_names: list[str] = []  # 校验通过后填充; 失败兜底清理只针对它
    try:
        require_tools()
        layout = discover(args.package_root, args.bios_dir, args.ec_dir)
        summary = validate(layout, _bios_fat_bytes())
        shell_efi = resolve_shell_efi(args.shell_efi)
        report.print_summary(summary)

        product_names = [iso_product_name(BUILD_SPECS[t], summary) for t in FlashTarget]
        if args.out_dir.is_dir():
            stale = sorted(p for p in args.out_dir.glob("*.iso") if p.name not in product_names)
            orphan_tmps = sorted(args.out_dir.glob("*.iso.tmp"))  # 中断/断电残留
            if stale or orphan_tmps:
                report.print_stale_products(stale, orphan_tmps)
        args.out_dir.mkdir(parents=True, exist_ok=True)
        products = [
            build_product(BUILD_SPECS[target], summary, shell_efi, args)
            for target in FlashTarget
        ]
        for i, p in enumerate(products, start=1):
            report.print_product(i, len(products), p.target, p.iso, p.listing)
        report.print_next_steps([p.iso.name for p in products])
        if args.keep_stage:
            report.print_stage_note(args.out_dir / "stage")
    except ValidationError as exc:
        report.print_error(f"{exc.what}\n  修复指引: {exc.hint}")
        return 2
    except BuildError as exc:
        return _abort_build(args, product_names, str(exc))
    except (OSError, UnicodeDecodeError) as exc:
        # 未预期的 I/O / 解码错误也归入 3, 保持 0/2/3 契约, 不裸抛 traceback
        return _abort_build(args, product_names, f"未预期的 I/O 错误: {exc!r}")
    return 0


def _bios_fat_bytes() -> int:
    """BIOS 盘 FAT 镜像容量 (字节), 注入 validate 做 bin 尺寸上限校验."""
    return BUILD_SPECS[FlashTarget.BIOS].fat_size_mib * 1024 * 1024


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
