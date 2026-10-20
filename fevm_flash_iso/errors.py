# 职责边界: 定义统一错误类型。ValidationError = 输入/环境不满足校验清单
# (fail fast, 带修复指引, CLI 退出码 2); BuildError = 外部工具执行失败或
# 产物自检失败 (CLI 退出码 3)。本模块不承载任何业务逻辑。

"""统一错误类型: 每个错误都携带 "出了什么事" 与 "怎么修" 两部分信息。"""

from collections.abc import Sequence
from dataclasses import dataclass
from subprocess import CompletedProcess


class ValidationError(Exception):
    """输入包/环境不满足校验清单, 必须终止 (绝不在校验失败时继续构建)."""

    def __init__(self, what: str, hint: str) -> None:
        super().__init__(f"{what}\n修复指引: {hint}")
        self.what = what
        self.hint = hint


@dataclass(frozen=True)
class BuildFailure:
    """一次外部工具失败的原始证据 (命令行 + 退出码 + 输出摘录)."""

    cmd: Sequence[str]
    returncode: int
    stderr: str
    stdout: str


class BuildError(Exception):
    """外部工具 (truncate/mkfs.vfat/mcopy/xorriso/mdir) 执行失败或产物自检失败."""

    def __init__(self, message: str, failure: BuildFailure | None = None) -> None:
        detail = message
        if failure is not None:
            detail += f"\n命令: {' '.join(failure.cmd)}\n退出码: {failure.returncode}"
            if failure.stderr.strip():
                detail += f"\nstderr: {failure.stderr.strip()[-2000:]}"
            if failure.stdout.strip():
                detail += f"\nstdout: {failure.stdout.strip()[-2000:]}"
        super().__init__(detail)
        self.message = message
        self.failure = failure


def build_failure_from_proc(
    message: str, cmd: Sequence[str], proc: CompletedProcess[str]
) -> BuildError:
    """把一次失败的 subprocess 结果包装为带诊断信息的 BuildError."""
    return BuildError(
        message,
        BuildFailure(cmd=cmd, returncode=proc.returncode, stderr=proc.stderr, stdout=proc.stdout),
    )
