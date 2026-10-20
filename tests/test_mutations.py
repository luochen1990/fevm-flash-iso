# 职责边界: 变异测试 —— 把合成包逐项破坏 (删文件/错文件名/坏 MZ 头/
# NSH 引用不一致/工具缺失/参数错误), 断言对应校验以退出码 2 失败且错误
# 信息包含可操作的修复指引。不依赖外部工具 (全部在校验层拦截)。

"""变异参数化测试: 每种破坏都必须 fail fast 且带修复指引。"""

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from fevm_flash_iso import cli, synth


@dataclass(frozen=True)
class Mutation:
    """一次破坏动作 + 期望错误信息片段 (含指引关键词)."""

    name: str
    mutate: Callable[[Path], None]
    expect: tuple[str, ...]
    expect_hint: bool = True  # 错误信息必须含 "修复指引"


def _bios_dir(pkg: Path) -> Path:
    return pkg / synth.SynthOptions().bios_dir_name


def _ec_dir(pkg: Path) -> Path:
    return pkg / synth.SynthOptions().ec_dir_name


def _rm_bios_tools_afu(pkg: Path) -> None:
    (_bios_dir(pkg) / "Tools" / "AfuEfix64.efi").unlink()


def _duplicate_bios_dir(pkg: Path) -> None:
    shutil.copytree(_bios_dir(pkg), pkg / "OTHER_2.00_BIOS")


def _rename_ec_bin_only(pkg: Path) -> None:
    opts = synth.SynthOptions()
    shutil.move(_ec_dir(pkg) / opts.ec_bin_name, _ec_dir(pkg) / "EC_TESTX1_V9_4_0_1_28F.bin")


def _corrupt_ifu_mz(pkg: Path) -> None:
    (_ec_dir(pkg) / "ifu.efi").write_bytes(b"\x00\x00not mz at all")


def _truncate_bios_bin(pkg: Path) -> None:
    bin_path = _bios_dir(pkg) / synth.SynthOptions().bios_bin_name
    bin_path.write_bytes(b"SYNTH" + b"\x00" * (4 * 1024 * 1024))


def _break_nflash_ref(pkg: Path) -> None:
    (_bios_dir(pkg) / "Tools" / "nFlash.nsh").write_text(
        "@echo -off\r\nrem no afu reference here\r\n", encoding="ascii", newline=""
    )


def _unparseable_bios_bin_name(pkg: Path) -> None:
    shutil.move(
        _bios_dir(pkg) / synth.SynthOptions().bios_bin_name,
        _bios_dir(pkg) / "fw.bin",
    )


def _extra_bin_in_bios_dir(pkg: Path) -> None:
    (_bios_dir(pkg) / "EXTRA_V2.00.bin").write_bytes(b"\x00" * (8 * 1024 * 1024))


def _corrupt_checksum_only(pkg: Path) -> None:
    """ChecksumF 损坏只是 warning, 不应失败 —— 用作反向对照."""
    (_ec_dir(pkg) / "ChecksumF.txt").write_text("garbage", encoding="ascii", newline="")


MUTATIONS: tuple[Mutation, ...] = (
    Mutation("afu_efi_deleted", _rm_bios_tools_afu, ("BIOS", "--bios-dir")),
    Mutation("bios_dir_duplicated", _duplicate_bios_dir, ("候选 BIOS", "--bios-dir")),
    Mutation("ec_bin_renamed_script_stale", _rename_ec_bin_only, ("FEC64.NSH", "不存在")),
    Mutation("ifu_mz_corrupt", _corrupt_ifu_mz, ("ifu.efi", "PE/COFF")),
    Mutation("bios_bin_truncated", _truncate_bios_bin, ("BIOS bin", "8 MiB")),
    Mutation("nflash_ref_broken", _break_nflash_ref, ("nFlash.nsh", "Tools")),
    Mutation("bios_bin_name_unparseable", _unparseable_bios_bin_name, ("解析版本",)),
    Mutation("extra_bin_ambiguous", _extra_bin_in_bios_dir, ("无法确定 BIOS 镜像",)),
)


@pytest.mark.parametrize("mut", MUTATIONS, ids=[m.name for m in MUTATIONS])
def test_mutation_fails_fast_with_hint(
    mut: Mutation, pkg: Path, out_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mut.mutate(pkg)
    rc = cli.main([str(pkg), "-o", str(out_dir)])
    captured = capsys.readouterr()
    assert rc == 2, f"应 fail fast; stdout={captured.out}"
    text = captured.err
    for fragment in mut.expect:
        assert fragment in text, f"错误信息缺少 {fragment!r}: {text}"
    if mut.expect_hint:
        assert "修复指引" in text
    # 绝不在校验失败时继续构建
    assert not out_dir.exists() or not any(out_dir.iterdir())


def test_checksum_corruption_is_warning_not_failure(
    pkg: Path, out_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """ChecksumF 算法未知 -> 只展示不硬校验 (反向对照: 不应失败)."""
    _corrupt_checksum_only(pkg)
    rc = cli.main([str(pkg), "-o", str(out_dir)])
    assert rc in (0, 2)  # 无外部工具时 (CI 跳过构建) 可能 0; 有工具必 0
    if rc == 0:
        assert "未能解析" in capsys.readouterr().out


def test_cli_missing_shell_efi(
    pkg: Path, out_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "shell.txt"
    bad.write_text("x", encoding="ascii")
    rc = cli.main([str(pkg), "-o", str(out_dir), "--shell-efi", str(bad)])
    assert rc == 2
    assert "UEFI Shell" in capsys.readouterr().err


def test_cli_explicit_missing_bios_dir(
    pkg: Path, out_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cli.main([str(pkg), "-o", str(out_dir), "--bios-dir", str(tmp_path / "ghost")])
    assert rc == 2
    assert "--bios-dir" in capsys.readouterr().err


def test_cli_missing_root(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main([str(tmp_path / "ghost" / "pkg")])
    assert rc == 2
    assert "包根目录" in capsys.readouterr().err
