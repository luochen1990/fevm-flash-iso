# 职责边界: 只做 "字符串 -> 结构化字段" 的解析 (纯函数, 无 IO, 无校验决策)。
# 解析对象: 机型名、BIOS bin 文件名 (BIOS 版本 + 内嵌 EC 版本)、EC bin
# 文件名 (下划线版本串)、ChecksumF.txt 条目。校验层负责把解析失败转成
# 可操作错误; 正则只提取关键字段, 不写死整串文件名。

"""固件文件名与版本号解析 (纯函数)。"""

import re
from dataclasses import dataclass

# BIOS bin: ..._V1.06_..._EC_V0.1.29_20260720.bin
# 负向后视排除 EC_V 前缀, 防止把内嵌 EC 版本误读成 BIOS 版本
BIOS_VERSION_RE = re.compile(r"(?<!EC_)V(\d+\.\d+)")
EMBEDDED_EC_RE = re.compile(r"EC_V([\d.]+)")
# EC bin: EC_FEVM_V9_4_0_1_29F.bin (下划线串转点分 => 9.4.0.1.29)
EC_BIN_RE = re.compile(r"^EC_(\w+?)_V(\d+(?:_\d+)+)(F?)\.bin$", re.IGNORECASE)
# ChecksumF.txt: [<bin名>] checksum : <8位hex> (ITE 私有算法, 仅供人工比对)
CHECKSUM_RE = re.compile(
    r"\[\s*([^\]\s][^\]]*?)\s*\]\s*checksum\s*:\s*([0-9A-Fa-f]{8})", re.IGNORECASE
)
# 目录名: 机型取首段下划线前的 token, 如 FAEX1_1.06_BIOS -> FAEX1
MODEL_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")


@dataclass(frozen=True)
class BiosBinName:
    """BIOS bin 文件名的解析结果 (版本均为裸数字串, 展示时自行加 V 前缀)."""

    raw: str
    bios_version: str  # "1.06"
    embedded_ec_version: str  # "0.1.29"

    @property
    def bios_display(self) -> str:
        return f"V{self.bios_version}"

    @property
    def embedded_ec_display(self) -> str:
        return f"V{self.embedded_ec_version}"


@dataclass(frozen=True)
class EcBinName:
    """EC bin 文件名的解析结果."""

    raw: str
    project: str  # EC_ 后的项目段, 实测为 FEVM
    version: str  # 下划线串转点分, 如 "9.4.0.1.29"
    f_suffix: bool  # 文件名是否带 F 后缀

    @property
    def display(self) -> str:
        return f"V{self.version}{'F' if self.f_suffix else ''}"


@dataclass(frozen=True)
class ChecksumEntry:
    """ChecksumF.txt 中一条记录: bin 名 + 8 位十六进制校验和."""

    bin_name: str
    hex8: str


def parse_bios_bin_name(name: str) -> BiosBinName | None:
    """解析 BIOS bin 文件名; 缺少 BIOS 版本或内嵌 EC 版本字段时返回 None."""
    bios = BIOS_VERSION_RE.search(name)
    embedded = EMBEDDED_EC_RE.search(name)
    if bios is None or embedded is None:
        return None
    return BiosBinName(
        raw=name, bios_version=bios.group(1), embedded_ec_version=embedded.group(1)
    )


def parse_ec_bin_name(name: str) -> EcBinName | None:
    """解析 EC bin 文件名 (EC_<项目>_V<数字(_数字)+><F?>.bin); 不匹配返回 None."""
    m = EC_BIN_RE.match(name)
    if m is None:
        return None
    return EcBinName(
        raw=name,
        project=m.group(1),
        version=m.group(2).replace("_", "."),
        f_suffix=bool(m.group(3)),
    )


def parse_model_dirname(name: str) -> str | None:
    """从目录名提取机型 (首个下划线前的 token); 无法提取返回 None."""
    head = name.split("_", 1)[0]
    if MODEL_NAME_RE.match(head) is None:
        return None
    return head


def parse_checksum_text(text: str) -> ChecksumEntry | None:
    """从 ChecksumF.txt 全文提取首条 checksum 记录; 无匹配返回 None."""
    m = CHECKSUM_RE.search(text)
    if m is None:
        return None
    return ChecksumEntry(bin_name=m.group(1), hex8=m.group(2).lower())


def release_tail(version: str) -> str:
    """取点分版本串的最后两个数字段 (release 段), 不足两段取整串.

    背景: EC 包版本 (9.4.0.1.29) 前三段是 ITE 工程版本, 真正与 BIOS 内嵌
    EC 版本 (0.1.29) 可对齐的是 release 尾段 (1.29)。
    """
    parts = version.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else version


def ec_versions_consistent(embedded_ec_version: str, ec_package_version: str) -> bool:
    """BIOS 内嵌 EC 版本与 EC 包版本做 release 尾段软一致性比较."""
    return release_tail(embedded_ec_version) == release_tail(ec_package_version)
