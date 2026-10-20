# 职责边界: pytest 共享夹具。合成包全部由 fevm_flash_iso.synth 程序生成,
# 绝不读取 /home/lc/Downloads 下的真实固件; 外部工具 (mkfs.vfat/mcopy/
# xorriso) 缺失时, 依赖它们的 golden/构建类测试整体跳过 (错误原因清晰)。

"""pytest 夹具: 合成固件包与外部工具探测。"""

import shutil
from pathlib import Path

import pytest

from fevm_flash_iso import synth

BUILD_TOOLS = ("truncate", "mkfs.vfat", "mcopy", "mdir", "xorriso")
requires_build_tools = pytest.mark.skipif(
    any(shutil.which(t) is None for t in BUILD_TOOLS),
    reason="构建类测试需要 mtools/dosfstools/xorriso (nix develop 提供)",
)


@pytest.fixture
def pkg(tmp_path: Path) -> Path:
    """标准合成固件包 (合法, 应全链路通过)."""
    return synth.synth_package(tmp_path / "pkg")


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    return tmp_path / "dist"
