# 职责边界: subprocess 封装 (唯一的进程出口)。run_ok = 非零退出码立即转
# BuildError (带命令行与 stderr 摘录); require_tools = 入口处集中检查外
# 部工具存在 (集中式预处理: 环境问题在构建开始前一次性暴露, 而不是在
# 构建到一半时崩)。

"""subprocess 封装与外部工具前置检查。"""

import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from .errors import ValidationError, build_failure_from_proc

# 管线依赖的外部工具 (nix develop 全部提供)
REQUIRED_TOOLS: tuple[str, ...] = ("truncate", "mkfs.vfat", "mcopy", "mdir", "xorriso")

NIX_ENV_HINT = (
    "在 NixOS 上进入开发环境: nix develop (或 nix-shell -p mtools dosfstools xorriso)"
)


def require_tools() -> None:
    """入口处检查 REQUIRED_TOOLS 全部可用, 缺失即 ValidationError."""
    missing = [t for t in REQUIRED_TOOLS if shutil.which(t) is None]
    if missing:
        raise ValidationError(
            f"缺少外部工具: {', '.join(missing)}",
            NIX_ENV_HINT,
        )


def run_ok(cmd: Sequence[str | Path], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """运行命令 (str/Path 混合的参数表会被统一转成 str); 非零退出码抛 BuildError."""
    argv = [str(c) for c in cmd]
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise build_failure_from_proc(f"命令执行失败: {argv[0]}", argv, proc)
    return proc
