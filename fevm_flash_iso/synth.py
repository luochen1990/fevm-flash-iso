# 职责边界: 合成 FEVM 固件包生成器 —— 测试与演示 (just build-demo) 专用,
# 不属于刷写管线。契约: 生成的包在目录结构与文件命名规约上与实测 FEVM
# 包同构, 但内容全部程序合成 (随机字节 bin、手工 PE 头的假 efi、自写
# 脚本), 绝不包含任何真实固件 —— 仓库公开后也不存在版权/隐私风险。
# bin 内容以 "SYNTHETIC-..." 标记开头, 从字节层面杜绝与真实固件混淆。

"""合成固件包生成器 (仅测试/演示用)。"""

import os
import struct
from dataclasses import dataclass
from pathlib import Path

_MIB = 1024 * 1024
_KIB = 1024


@dataclass(frozen=True)
class SynthOptions:
    """合成包的形态参数 (默认值与实测 FEVM FAEX1 包同构, 尺寸取测试友好值)."""

    model: str = "TESTX1"
    bios_version: str = "1.06"
    embedded_ec_version: str = "0.1.29"
    ec_project: str = "TESTX1"  # EC bin 名中 EC_ 后的项目段 (实测为 FEVM)
    ec_underscore_version: str = "9_4_0_1_29"
    ec_f_suffix: bool = True
    bios_bin_bytes: int = 8 * _MIB  # 最小合法尺寸, 加快测试; 真实包为 32 MiB
    ec_bin_bytes: int = 128 * _KIB
    with_checksum: bool = True
    date_tag: str = "20260101"

    @property
    def bios_dir_name(self) -> str:
        return f"{self.model}_{self.bios_version}_BIOS"

    @property
    def ec_dir_name(self) -> str:
        release = ".".join(self.ec_underscore_version.split("_")[-2:])
        return f"{self.model}_{release}EC"

    @property
    def bios_bin_name(self) -> str:
        return (
            f"{self.model}_FP11_STXH_TEST_S112_V{self.bios_version}"
            f"_M0TEST_8000_1_12_EC_V{self.embedded_ec_version}_{self.date_tag}.bin"
        )

    @property
    def ec_bin_name(self) -> str:
        suffix = "F" if self.ec_f_suffix else ""
        return f"EC_{self.ec_project}_V{self.ec_underscore_version}{suffix}.bin"


def fake_efi_bytes(machine: int = 0x8664, size: int = 8192, *, pseudo: bool = False) -> bytes:
    """构造带合法 MZ/PE/Machine/Magic/SizeOfHeaders 头的假 EFI 文件.

    pseudo=True 时只写 MZ/PE/Machine 三个字段, 其余随机 —— 模拟 "伪体"
    文件 (头部签名对了但 OptionalHeader 是垃圾), 用于测试 PE32+ 健全性
    校验的拒绝路径。
    """
    buf = bytearray(os.urandom(size))
    buf[0:2] = b"MZ"
    struct.pack_into("<I", buf, 0x3C, 0x40)
    buf[0x40:0x44] = b"PE\x00\x00"
    struct.pack_into("<H", buf, 0x44, machine)
    if not pseudo:
        struct.pack_into("<H", buf, 0x40 + 24, 0x20B)  # OptionalHeader Magic = PE32+
        struct.pack_into("<I", buf, 0x40 + 84, 0x200)  # SizeOfHeaders <= 文件长
    return bytes(buf)


def _synth_bin(path: Path, size: int, marker: str) -> None:
    """合成固件 bin: 标记头 + 随机填充, 尺寸精确等于 size."""
    head = marker.encode("ascii")
    path.write_bytes(head + os.urandom(max(size - len(head), 0)))


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="ascii", newline="")


def synth_package(dest: Path, opts: SynthOptions | None = None) -> Path:
    """在 dest 下生成一个完整合成固件包, 返回包根路径."""
    o = opts if opts is not None else SynthOptions()
    bios_dir = dest / o.bios_dir_name
    tools = bios_dir / "Tools"
    ec_dir = dest / o.ec_dir_name
    tools.mkdir(parents=True, exist_ok=True)
    ec_dir.mkdir(parents=True, exist_ok=True)

    # ---- BIOS 目录 (Windows 专用文件一并放入, 工具应忽略) ----
    _write(bios_dir / "Flash.cmd",
           '@echo off\r\nrem synthetic windows shim, ignored by fevm-flash-iso\r\n')
    _synth_bin(
        bios_dir / o.bios_bin_name, o.bios_bin_bytes, "SYNTHETIC-BIOS-IMAGE-NOT-REAL-FIRMWARE"
    )
    (tools / "AfuEfix64.efi").write_bytes(fake_efi_bytes(size=16384))
    (tools / "AFUWINx64.exe").write_bytes(b"MZ" + os.urandom(4096))  # 噪音文件
    _write(tools / "nFlash.nsh",
           "@echo -off\r\n"
           "\r\n"
           "rem synthetic vendor-style AFU launcher\r\n"
           'set Afu_arg " /CAPSULE /P /B /N /K /L /X /RLC:E"\r\n'
           "for %a in *bin\r\n"
           "  set bin_path_name %a\r\n"
           "endfor\r\n"
           "if exist %bin_path_name% then\r\n"
           '  .\\Tools\\AfuEfix64.efi "%bin_path_name%" %Afu_arg%\r\n'
           "endif\r\n")

    # ---- EC 目录 ----
    _synth_bin(ec_dir / o.ec_bin_name, o.ec_bin_bytes, "SYNTHETIC-EC-IMAGE-NOT-REAL-FIRMWARE")
    (ec_dir / "ifu.efi").write_bytes(fake_efi_bytes(size=8192))
    (ec_dir / "IFU_XE.exe").write_bytes(b"MZ" + os.urandom(4096))  # 噪音文件
    _write(ec_dir / "FEC64.NSH",
           "# synthetic ITE IT5570E eFlash update script\r\n"
           f"# FILENAME: EC_{o.ec_project}_V{o.ec_underscore_version}.bin\r\n"
           "mm 66 DD -w 1 -io\r\n"
           f"ifu {o.ec_bin_name} 0\r\n")
    _write(ec_dir / "uiset.ini",
           "[Info]\r\nACPI PORT=0x68\r\nAutoFlash=0\r\nShutdown=0\r\nBinName=ec.rom\r\nEND\r\n")
    if o.with_checksum:
        _write(ec_dir / "ChecksumF.txt",
               "\r\nsynthetic FU.EXE log\r\n"
               f"[{o.ec_bin_name}] checksum : deadbeef\r\n")

    # ---- 包根噪音文件 (工具应忽略) ----
    _write(dest / "release-notes.txt", "synthetic package\r\n")
    return dest
