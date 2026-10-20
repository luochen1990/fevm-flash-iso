# 职责边界: 包结构识别 (结构层校验 #1) —— 在包根的子目录中按内容指纹
# 识别出恰好一个 BIOS 目录 (*.bin + Tools/AfuEfix64.efi + Tools/nFlash.nsh)
# 和恰好一个 EC 目录 (EC_*.bin + ifu.efi + FEC64.NSH), 识别不出或有歧义
# 都立即失败并提示 --bios-dir/--ec-dir 显式指定。目录名可变, 一切按内容
# 识别; 文件名匹配大小写不敏感 (对 Windows 打包的包更稳)。

"""包结构识别: 内容指纹式发现 BIOS/EC 目录。"""

from dataclasses import dataclass
from pathlib import Path

from .errors import ValidationError
from .filenames import parse_ec_bin_name

BIOS_DIR_HINT = "BIOS 目录要素: 顶层恰一个 *.bin + Tools/AfuEfix64.efi + Tools/nFlash.nsh"
EC_DIR_HINT = "EC 目录要素: 恰一个 EC_*.bin + ifu.efi + FEC64.NSH"


@dataclass(frozen=True)
class BiosPayload:
    """BIOS 目录的结构化描述 (路径均存在, 内容校验在 validate 层)."""

    dir: Path
    bin_path: Path
    afu_efi: Path
    nflash_nsh: Path


@dataclass(frozen=True)
class EcPayload:
    """EC 目录的结构化描述 (uiset.ini / ChecksumF.txt 为可选项)."""

    dir: Path
    bin_path: Path
    ifu_efi: Path
    fec_nsh: Path
    uiset_ini: Path | None
    checksum_txt: Path | None


@dataclass(frozen=True)
class PackageLayout:
    """整个固件包的结构化布局."""

    root: Path
    bios: BiosPayload
    ec: EcPayload


def _find_child(parent: Path, name: str) -> Path | None:
    """大小写不敏感地查找 parent 的直接子项 (文件或目录)."""
    target = name.casefold()
    for child in parent.iterdir():
        if child.name.casefold() == target:
            return child
    return None


def _bios_pieces(d: Path) -> tuple[list[Path], Path | None, Path | None]:
    """提取 BIOS 目录要素: (bin 列表, AFU efi, nFlash.nsh)."""
    bins = sorted(p for p in d.iterdir() if p.is_file() and p.suffix.casefold() == ".bin")
    tools = _find_child(d, "Tools")
    afu = _find_child(tools, "AfuEfix64.efi") if tools is not None and tools.is_dir() else None
    nsh = _find_child(tools, "nFlash.nsh") if tools is not None and tools.is_dir() else None
    return bins, afu, nsh


def _inspect_bios_dir(d: Path) -> BiosPayload | tuple[str, ...]:
    """单次检查 BIOS 目录要素: 成功返回 payload; 失败返回缺失要素清单;
    有歧义 (多个 bin, 无法安全选择) 直接抛 ValidationError."""
    bins, afu, nsh = _bios_pieces(d)
    if len(bins) > 1:
        raise ValidationError(
            f"目录 {d.name} 含 {len(bins)} 个 .bin 文件: "
            f"{[p.name for p in bins]}, 无法确定 BIOS 镜像",
            "BIOS 目录顶层只应有一个 .bin; 清理多余文件或用 --bios-dir 显式指定",
        )
    if not bins or afu is None or nsh is None:
        missing: list[str] = []
        if not bins:
            missing.append("顶层 *.bin (BIOS 镜像)")
        if afu is None:
            missing.append("Tools/AfuEfix64.efi")
        if nsh is None:
            missing.append("Tools/nFlash.nsh")
        return tuple(missing)
    return BiosPayload(dir=d, bin_path=bins[0], afu_efi=afu, nflash_nsh=nsh)


def _ec_pieces(d: Path) -> tuple[list[Path], Path | None, Path | None]:
    """提取 EC 目录要素: (EC bin 列表, ifu.efi, FEC64.NSH)."""
    bins = sorted(
        p for p in d.iterdir() if p.is_file() and parse_ec_bin_name(p.name) is not None
    )
    return bins, _find_child(d, "ifu.efi"), _find_child(d, "FEC64.NSH")


def _inspect_ec_dir(d: Path) -> EcPayload | tuple[str, ...]:
    """单次检查 EC 目录要素: 成功返回 payload; 失败返回缺失要素清单; 多 bin 抛错."""
    bins, ifu, fec = _ec_pieces(d)
    if len(bins) > 1:
        raise ValidationError(
            f"目录 {d.name} 含 {len(bins)} 个 EC bin 文件: "
            f"{[p.name for p in bins]}, 无法确定 EC 镜像",
            "EC 目录内只应有一个 EC bin; 清理多余文件或用 --ec-dir 显式指定",
        )
    if not bins or ifu is None or fec is None:
        missing: list[str] = []
        if not bins:
            missing.append("匹配 EC_<项目>_V<数字(_数字)+><F?>.bin 规约的 bin")
        if ifu is None:
            missing.append("ifu.efi")
        if fec is None:
            missing.append("FEC64.NSH")
        return tuple(missing)
    return EcPayload(
        dir=d,
        bin_path=bins[0],
        ifu_efi=ifu,
        fec_nsh=fec,
        uiset_ini=_find_child(d, "uiset.ini"),
        checksum_txt=_find_child(d, "ChecksumF.txt"),
    )


def _match_bios_dir(d: Path) -> BiosPayload:
    """显式指定的 BIOS 目录: 要素不全时按缺失清单报错."""
    result = _inspect_bios_dir(d)
    if isinstance(result, tuple):
        raise ValidationError(
            f"目录 {d} 缺少 BIOS 目录要素: {', '.join(result)}",
            f"确认指向正确的 BIOS 目录 ({BIOS_DIR_HINT})",
        )
    return result


def _match_ec_dir(d: Path) -> EcPayload:
    """显式指定的 EC 目录: 要素不全时按缺失清单报错."""
    result = _inspect_ec_dir(d)
    if isinstance(result, tuple):
        raise ValidationError(
            f"目录 {d} 缺少 EC 目录要素: {', '.join(result)}",
            f"确认指向正确的 EC 目录 ({EC_DIR_HINT})",
        )
    return result


def _select_one(root: Path, kind: str, candidates: list[Path]) -> Path:
    """从候选目录中选出恰好一个; 零个或多个都抛错并提示显式指定参数."""
    flag = "--bios-dir" if kind == "BIOS" else "--ec-dir"
    hint_line = BIOS_DIR_HINT if kind == "BIOS" else EC_DIR_HINT
    if not candidates:
        raise ValidationError(
            f"在 {root} 的子目录中未识别出 {kind} 目录 ({hint_line})",
            f"确认包结构完整; 若目录名/层级特殊, 用 {flag} <路径> 显式指定",
        )
    if len(candidates) > 1:
        raise ValidationError(
            f"在 {root} 下识别出 {len(candidates)} 个候选 {kind} 目录: "
            f"{[c.name for c in candidates]}, 无法自动选择",
            f"删除多余的候选目录, 或用 {flag} <路径> 显式指定其一",
        )
    return candidates[0]


def _scan_bios(root: Path) -> list[Path]:
    """按内容指纹找出候选 BIOS 目录 (要素不全的目录被跳过, 歧义目录抛错)."""
    candidates: list[Path] = []
    for d in sorted(root.iterdir()):
        if d.is_dir() and not d.name.startswith("."):
            result = _inspect_bios_dir(d)
            if not isinstance(result, tuple):
                candidates.append(d)
    return candidates


def _scan_ec(root: Path) -> list[Path]:
    """按内容指纹找出候选 EC 目录 (要素不全的目录被跳过, 歧义目录抛错)."""
    candidates: list[Path] = []
    for d in sorted(root.iterdir()):
        if d.is_dir() and not d.name.startswith("."):
            result = _inspect_ec_dir(d)
            if not isinstance(result, tuple):
                candidates.append(d)
    return candidates


def discover(root: Path, bios_dir: Path | None, ec_dir: Path | None) -> PackageLayout:
    """结构层校验入口: 返回包布局; 任何结构问题立即抛 ValidationError.

    bios_dir/ec_dir 为显式覆盖 (跳过自动识别, 但仍校验目录要素)。
    """
    if not root.is_dir():
        raise ValidationError(
            f"包根目录不存在或不是目录: {root}",
            "路径应指向 FEVM 固件包根目录 (其下有 BIOS 目录与 EC 目录)",
        )
    bios_path = bios_dir if bios_dir is not None else _select_one(root, "BIOS", _scan_bios(root))
    ec_path = ec_dir if ec_dir is not None else _select_one(root, "EC", _scan_ec(root))
    if not bios_path.is_dir():
        raise ValidationError(f"--bios-dir 指向的目录不存在: {bios_path}", "检查路径或改用自动识别")
    if not ec_path.is_dir():
        raise ValidationError(f"--ec-dir 指向的目录不存在: {ec_path}", "检查路径或改用自动识别")
    return PackageLayout(root=root, bios=_match_bios_dir(bios_path), ec=_match_ec_dir(ec_path))
