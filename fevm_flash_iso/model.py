# 职责边界: 全仓库共享的代数数据类型与常量 (纯数据, 无 IO)。
# 刷写目标枚举、各目标构建参数 (实测验证, 参数语义不可改)、FAT 镜像布局
# 常量、内容层校验阈值, 全部集中于此, 避免魔法字符串散落各模块。

"""核心数据模型: 刷写目标、构建参数与布局常量。"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType


class FlashTarget(Enum):
    """刷写目标: BIOS (AMI AFU capsule 模式) 或 EC (ITE ifu)."""

    BIOS = "BIOS"
    EC = "EC"


@dataclass(frozen=True)
class BuildSpec:
    """单个刷写目标的构建参数。

    契约: 以下参数来自 2026-10 实机验证的构建管线 (Ventoy 引导 + FEVM
    FAEX1 实测刷写成功), 修改任何一项都可能造出不可引导/不可刷写的盘:

    - fat_size_mib / fat_sectors_per_cluster: FAT 引导镜像几何。BIOS 盘
      64MiB; EC 盘 8MiB。显式 sectors-per-cluster 是因为 dosfstools 4.2
      的自动簇适配在 8MiB 上选不出合法 FAT16 参数 (簇数出界), 显式固定
      几何同时保证跨版本可复现。
    - payload_entry: 厂商脚本在 payload 目录内的入口路径, 同时是
      startup.nsh 探测循环的探测文件 (目标路径唯一命中)。
    """

    target: FlashTarget
    fat_size_mib: int
    fat_sectors_per_cluster: int
    fat_label: str
    iso_volid: str
    payload_dir: str
    payload_entry: str

    @property
    def probe_path(self) -> str:
        """startup.nsh 探测循环用的完整路径, 如 ``fs%z:\\0_Afu_Flash\\Tools\\nFlash.nsh``."""
        return f"{self.payload_dir}\\{self.payload_entry}"


BUILD_SPECS: Mapping[FlashTarget, BuildSpec] = MappingProxyType(
    {
        FlashTarget.BIOS: BuildSpec(
            target=FlashTarget.BIOS,
            fat_size_mib=64,
            fat_sectors_per_cluster=4,  # 64MiB/512B扇区/4扇区簇 ~= 32K 簇, 合法 FAT16
            fat_label="FEVMBIOS",
            iso_volid="FEVM_FLASH_BIOS",
            payload_dir="0_Afu_Flash",
            payload_entry="Tools\\nFlash.nsh",
        ),
        FlashTarget.EC: BuildSpec(
            target=FlashTarget.EC,
            fat_size_mib=8,
            fat_sectors_per_cluster=1,  # 8MiB/512B扇区/1扇区簇 ~= 16K 簇, 合法 FAT16
            fat_label="FEVMEC",
            iso_volid="FEVM_FLASH_EC",
            payload_dir="EC",
            payload_entry="FEC64.NSH",
        ),
    }
)

# ---- FAT 镜像内固定布局 (startup.nsh 探测路径与 stage 布局必须与之同步) ----
EFI_BOOT_DIR = "EFI/BOOT"
BOOT_EFI_NAME = "BOOTX64.EFI"
STARTUP_NSH_NAME = "startup.nsh"
README_NAME = "README.txt"
BOOT_EFI_REL = f"{EFI_BOOT_DIR}/{BOOT_EFI_NAME}"
EFI_IMG_NAME = "efi.img"

# ---- 内容层校验阈值 ----
BIOS_BIN_MIN_BYTES = 8 * 1024 * 1024  # 实测 FEVM BIOS bin 为 32 MiB
EC_BIN_ALLOWED_BYTES = frozenset({64 * 1024, 128 * 1024, 256 * 1024, 512 * 1024})
PE_MACHINE_AMD64 = 0x8664
