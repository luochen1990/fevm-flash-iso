# 职责边界: 内容层校验 (#2-#7) 与解析摘要。输入结构层产出的 PackageLayout,
# 依次执行: EFI 文件 PE/COFF x64 校验、bin 尺寸校验、厂商脚本交叉引用
# 校验 (FEC64.NSH <-> EC bin, nFlash.nsh <-> Tools/AfuEfix64.efi)、文件名
# 版本解析、软一致性检查 (BIOS 内嵌 EC 版本 vs EC 包版本) 与 ChecksumF
# 信息展示。任何硬校验失败立即抛 ValidationError (fail fast); 软问题以
# warning 记录在摘要里, 不阻断构建。

"""内容层校验与解析摘要。"""

import re
from dataclasses import dataclass
from pathlib import Path

from .discover import PackageLayout
from .errors import ValidationError
from .filenames import (
    BiosBinName,
    ChecksumEntry,
    EcBinName,
    ec_versions_consistent,
    parse_bios_bin_name,
    parse_checksum_text,
    parse_ec_bin_name,
    parse_model_dirname,
)
from .model import BIOS_BIN_MIN_BYTES, EC_BIN_ALLOWED_BYTES
from .pecoff import validate_efi_amd64

# FEC64.NSH 中所有形如 EC bin 文件名的 token (含注释行中的引用)
EC_BIN_REF_RE = re.compile(r"EC_\w+_V\d+(?:_\d+)*F?\.bin", re.IGNORECASE)
# FEC64.NSH 中真正执行刷写的 ifu 命令行: ifu <bin名> [参数]
IFU_LINE_RE = re.compile(r"(?im)^\s*ifu\s+(\S+)")
# nFlash.nsh 对 AFU 工具的相对路径引用约定 (大小写不敏感)
NFLASH_AFU_REF = "tools\\afuefix64.efi"


@dataclass(frozen=True)
class FirmwareSummary:
    """解析与校验的最终摘要: 构建层与报告层只依赖此快照."""

    layout: PackageLayout
    model: str
    bios_bin: BiosBinName
    ec_bin: EcBinName
    ec_consistent: bool
    checksum: ChecksumEntry | None
    warnings: tuple[str, ...]
    bios_bin_bytes: int
    ec_bin_bytes: int


def _read_text_guess(path: Path) -> str:
    """读取厂商脚本/文本: UTF-16 按 BOM 判定, 其余按 latin-1 无损解码.

    厂商脚本实测为 ASCII+CRLF; latin-1 保证任意字节流不抛异常, 后续
    全部用正则提取, 编码差异不影响结果。
    """
    data = path.read_bytes()
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16")
    return data.decode("latin-1")


def _check_efi_files(layout: PackageLayout) -> None:
    """校验清单 #2: 所有被消费的 .efi 必须是 PE/COFF AMD64."""
    validate_efi_amd64(layout.bios.afu_efi, role="BIOS 刷写工具")
    validate_efi_amd64(layout.ec.ifu_efi, role="EC 刷写工具")


def _check_bin_sizes(layout: PackageLayout, bios_fat_bytes: int) -> tuple[int, int]:
    """校验清单 #5: BIOS bin >= 8MiB (实测 32MiB) 且 < FAT 容量 x 0.9;
    EC bin in {64K,128K,256K,512K} (实测 128K).

    契约 (m-6 防什么事故): 过大的 BIOS bin 若不在此拦截, 会推进到 mcopy
    才以裸 mtools stderr 失败; 提前以可读错误终止。
    """
    bios_bytes = layout.bios.bin_path.stat().st_size
    ec_bytes = layout.ec.bin_path.stat().st_size
    if bios_bytes < BIOS_BIN_MIN_BYTES:
        raise ValidationError(
            f"BIOS bin 尺寸 {bios_bytes} 字节 ({bios_bytes / 1048576:.1f} MiB) 低于下限 "
            f"{BIOS_BIN_MIN_BYTES // 1048576} MiB (实测 FEVM BIOS 镜像为 32 MiB)",
            "确认 bin 文件没有下载截断或复制不完整",
        )
    bios_fat_limit = bios_fat_bytes * 0.9
    if bios_bytes >= bios_fat_limit:
        raise ValidationError(
            f"BIOS bin 尺寸 {bios_bytes / 1048576:.1f} MiB 达到或超过 FAT 引导镜像容量 "
            f"({bios_fat_bytes // 1048576} MiB) 的 90%, FAT 镜像装不下",
            "FAT 镜像装不下, 请确认是否拿错文件 (实测 FEVM BIOS 镜像为 32 MiB)",
        )
    if ec_bytes not in EC_BIN_ALLOWED_BYTES:
        allowed = ", ".join(f"{n // 1024}K" for n in sorted(EC_BIN_ALLOWED_BYTES))
        raise ValidationError(
            f"EC bin 尺寸 {ec_bytes} 字节不在允许集合 {{{allowed}}} 内 (实测 FEVM EC 镜像为 128K)",
            "确认 EC bin 文件完整, 与 FEC64.NSH 引用的是同一版本",
        )
    return bios_bytes, ec_bytes


def _check_nflash_ref(layout: PackageLayout) -> None:
    """校验清单 #4: nFlash.nsh 内容必须引用 .\\Tools\\AfuEfix64.efi.

    契约 (防什么事故): ISO 布局保持厂商脚本的相对路径约定 (bin 在当前
    目录、AFU 在 .\\Tools 下); 若脚本不再引用该路径, 打包后 AFU 将找不
    到, 刷写必然失败。
    """
    text = _read_text_guess(layout.bios.nflash_nsh).casefold()
    if NFLASH_AFU_REF not in text:
        raise ValidationError(
            f"nFlash.nsh ({layout.bios.nflash_nsh}) 未引用 .\\Tools\\AfuEfix64.efi 相对路径",
            "厂商脚本的相对路径约定被改动; 恢复原版 nFlash.nsh 或同步调整打包布局",
        )


def _check_fec_ref(layout: PackageLayout) -> None:
    """校验清单 #3: FEC64.NSH 与目录内实际 bin 双向一致.

    双通道契约 (m-3, 防什么事故):
    1. 严格通道 —— 每条非注释 ``ifu <name>`` 行引用的文件必须存在于目录
       (换固件版本时只改了目录没改脚本/或脚本 ifu 行指向不存在的名字,
       在此拦截);
    2. 宽松通道 —— 实际 bin 名 ∈ 全文 EC bin token 集合 (向后兼容: 实测
       厂商脚本注释头会引用旧版本名, 只要 ifu 行引用的文件真实存在且
       实际名被引用即放行)。
    """
    text = _read_text_guess(layout.ec.fec_nsh)
    present = {p.name.casefold() for p in layout.ec.dir.iterdir() if p.is_file()}
    ifu_refs = IFU_LINE_RE.findall(text)
    # minor-1: 完全没有 ifu 执行行 => 造出的是 "静默无操作" 的 EC 盘, 必须硬失败
    if not ifu_refs:
        raise ValidationError(
            f"FEC64.NSH ({layout.ec.fec_nsh}) 中未找到任何 ifu 刷写行",
            "请确认文件完整 (合法脚本应含 'ifu <bin> 0' 形式的执行行)",
        )
    missing = [ref for ref in ifu_refs if ref.casefold() not in present]
    if missing:
        raise ValidationError(
            f"FEC64.NSH 的 ifu 行引用了目录中不存在的文件: {missing}",
            "同步修改 FEC64.NSH 的 ifu 行, 使其只引用目录内真实存在的 bin",
        )
    tokens = {m.group(0).casefold() for m in EC_BIN_REF_RE.finditer(text)}
    actual = layout.ec.bin_path.name.casefold()
    if actual not in tokens:
        raise ValidationError(
            f"FEC64.NSH 引用的 EC bin 与目录内实际 bin 不一致: 脚本引用 {sorted(tokens)}, "
            f"实际为 {layout.ec.bin_path.name}",
            "换版本时须同步修改 FEC64.NSH 中的 ifu 行, 使其引用新 bin 文件名",
        )


def _parse_versions(layout: PackageLayout) -> tuple[BiosBinName, EcBinName]:
    """文件名版本解析 (校验清单 #6 的输入); 多个 BIOS 版本候选时硬失败
    (宁可不构建也不错标 ISO 文件名)."""
    try:
        bios_bin = parse_bios_bin_name(layout.bios.bin_path.name)
    except ValueError as exc:
        raise ValidationError(
            f"{exc} (文件: {layout.bios.bin_path.name})",
            "文件名含多个互不相同的 _V<x.y>_ 字段, 无法唯一确定 BIOS 版本; "
            "清理或重命名后重跑",
        ) from exc
    if bios_bin is None:
        raise ValidationError(
            f"无法从 BIOS bin 文件名解析版本: {layout.bios.bin_path.name}",
            "期望含 _V<版本>_ 与 EC_V<版本> 字段 (如 ..._V1.06_..._EC_V0.1.29_20260720.bin)",
        )
    ec_bin = parse_ec_bin_name(layout.ec.bin_path.name)
    if ec_bin is None:
        raise ValidationError(
            f"无法从 EC bin 文件名解析版本: {layout.ec.bin_path.name}",
            "期望形如 EC_<项目>_V<数字_数字...><F?>.bin (如 EC_FEVM_V9_4_0_1_29F.bin)",
        )
    return bios_bin, ec_bin


def _resolve_model(layout: PackageLayout, warnings: list[str]) -> str:
    """机型名: 优先 BIOS 目录名首段, EC 目录名为回退; 两者不一致时告警."""
    from_bios = parse_model_dirname(layout.bios.dir.name)
    from_ec = parse_model_dirname(layout.ec.dir.name)
    if from_bios is not None and from_ec is not None and from_bios != from_ec:
        warnings.append(
            f"BIOS 目录名与 EC 目录名解析出的机型不一致 "
            f"({from_bios} vs {from_ec}), 以 BIOS 目录为准"
        )
    model = from_bios or from_ec
    if model is None:
        raise ValidationError(
            f"无法从目录名解析机型名 (BIOS 目录: {layout.bios.dir.name}, "
            f"EC 目录: {layout.ec.dir.name})",
            "目录名应形如 <机型>_x.xx_BIOS / <机型>_x.xxEC (如 TESTX1_1.06_BIOS)",
        )
    return model


def _checksum_info(
    layout: PackageLayout,
    ec_bin: EcBinName,
    warnings: list[str],
) -> ChecksumEntry | None:
    """校验清单 #7: ChecksumF.txt 存在则解析并展示; 算法未知, 不做硬校验."""
    txt = layout.ec.checksum_txt
    if txt is None:
        return None
    entry = parse_checksum_text(_read_text_guess(txt))
    if entry is None:
        warnings.append(f"ChecksumF.txt ({txt}) 存在但未能解析出 '[bin] checksum : 8hex' 记录")
        return None
    if entry.bin_name.casefold() != ec_bin.raw.casefold():
        warnings.append(
            f"ChecksumF.txt 记录的 bin 名 ({entry.bin_name}) 与实际 ({ec_bin.raw}) 不一致"
        )
    return entry


def validate(layout: PackageLayout, bios_fat_bytes: int) -> FirmwareSummary:
    """内容层校验入口: 全部通过则返回摘要快照, 否则抛 ValidationError.

    bios_fat_bytes 为 BIOS 盘 FAT 引导镜像容量 (字节), 用于 bin 尺寸上限
    校验; 由调用方从 BUILD_SPECS 注入, 保持本模块纯函数。
    """
    warnings: list[str] = []

    bios_bin, ec_bin = _parse_versions(layout)
    _check_efi_files(layout)
    bios_bytes, ec_bytes = _check_bin_sizes(layout, bios_fat_bytes)
    _check_nflash_ref(layout)
    _check_fec_ref(layout)
    model = _resolve_model(layout, warnings)
    checksum = _checksum_info(layout, ec_bin, warnings)

    consistent = ec_versions_consistent(bios_bin.embedded_ec_version, ec_bin.version)
    if not consistent:
        warnings.append(
            f"BIOS 内嵌 EC 版本 {bios_bin.embedded_ec_display} 与 EC 包版本 {ec_bin.display} "
            "的 release 尾段不一致; 两者可独立发布, 请确认这不是版本拿混了"
        )

    return FirmwareSummary(
        layout=layout,
        model=model,
        bios_bin=bios_bin,
        ec_bin=ec_bin,
        ec_consistent=consistent,
        checksum=checksum,
        warnings=tuple(warnings),
        bios_bin_bytes=bios_bytes,
        ec_bin_bytes=ec_bytes,
    )
