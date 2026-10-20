# 职责边界: 原子发布与失败兜底测试 (M-1) + 统一错误出口 (m-7) +
# 陈旧产物提醒 (m-8)。全部通过 monkeypatch 模拟构建/自检失败, 断言
# 退出码契约与输出目录零残留。构建类场景需要外部工具, 缺失时跳过。

"""CLI 原子发布与错误出口测试。"""

from pathlib import Path

import pytest
from conftest import requires_build_tools

from fevm_flash_iso import cli
from fevm_flash_iso.errors import BuildError, ValidationError
from fevm_flash_iso.iso import verify_iso

pytestmark = requires_build_tools

BIOS_ISO = "TESTX1_FLASH_BIOS_V1.06.iso"
EC_ISO = "TESTX1_FLASH_EC_V9.4.0.1.29F.iso"


def _leftovers(out_dir: Path) -> tuple[str, ...]:
    """输出目录中的产物残留 (任何 .iso 或 .tmp)."""
    isos = sorted(p.name for p in out_dir.glob("*.iso"))
    tmps = sorted(p.name for p in out_dir.glob("*.tmp"))
    return tuple(isos + tmps)


@pytest.fixture
def fail_verify_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """让所有产物的自检失败."""
    def fake_verify(iso: Path, *_: object, **__: object) -> None:
        raise BuildError(f"boom: {iso.name}")

    monkeypatch.setattr(cli, "verify_iso", fake_verify)


@pytest.fixture
def fail_verify_ec_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """只让 EC 盘的自检失败 (BIOS 盘应已成功发布, 随后被兜底清理)."""
    real_verify = verify_iso

    def fake_verify(iso: Path, *args: object, **kwargs: object) -> None:
        if "FLASH_EC" in iso.name:
            raise BuildError(f"boom: {iso.name}")
        real_verify(iso, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cli, "verify_iso", fake_verify)


def test_verify_failure_leaves_no_products(
    pkg: Path, out_dir: Path, fail_verify_all: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """M-1: 自检失败 => rc=3, 输出目录无任何 .iso/.tmp, 且报告作废清单."""
    assert cli.main([str(pkg), "-o", str(out_dir)]) == 3
    assert _leftovers(out_dir) == ()
    captured = capsys.readouterr()
    assert "boom" in captured.err
    assert "已作废并清理" in captured.out
    assert ".iso.tmp" in captured.out


def test_partial_success_cleaned_up(
    pkg: Path, out_dir: Path, fail_verify_ec_only: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """M-1: BIOS 成功、EC 失败 => 本次已发布的 BIOS ISO 也被兜底清理."""
    assert cli.main([str(pkg), "-o", str(out_dir)]) == 3
    assert _leftovers(out_dir) == ()
    assert BIOS_ISO in capsys.readouterr().out  # 作废清单里含已发布的 BIOS 盘


def test_atomic_publish_no_tmp_on_success(pkg: Path, out_dir: Path) -> None:
    """成功路径: 只有最终名, 无 .tmp 残留 (原子发布)."""
    assert cli.main([str(pkg), "-o", str(out_dir)]) == 0
    assert _leftovers(out_dir) == (BIOS_ISO, EC_ISO)


def test_stale_products_warning(
    pkg: Path, out_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """m-8: 输出目录已有旧产物 => 醒目提醒; 同名重建不告警."""
    out_dir.mkdir(parents=True)
    (out_dir / "TESTX1_FLASH_BIOS_V9.99.iso").write_bytes(b"old")
    assert cli.main([str(pkg), "-o", str(out_dir)]) == 0
    out = capsys.readouterr().out
    assert "旧版本产物" in out
    assert "TESTX1_FLASH_BIOS_V9.99.iso" in out
    # 同名产物 (本次将原子替换) 不算旧产物
    assert out.count(BIOS_ISO) >= 1  # 正常产物报告仍然存在
    assert "已作废" not in out


def test_orphan_tmp_warning(
    pkg: Path, out_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """nit-2: 中断残留的 *.iso.tmp 单独提醒, 文案与旧版本产物区分."""
    out_dir.mkdir(parents=True)
    (out_dir / "TESTX1_FLASH_BIOS_V9.99.iso.tmp").write_bytes(b"interrupted")
    assert cli.main([str(pkg), "-o", str(out_dir)]) == 0
    out = capsys.readouterr().out
    assert "中断的残留文件" in out
    assert "TESTX1_FLASH_BIOS_V9.99.iso.tmp" in out
    assert "旧版本产物" not in out  # 没有 *.iso 时不出旧产物文案
    # 只提醒不代删: 孤儿 tmp 保留由用户处理; 本次运行自身不留任何 tmp
    assert (out_dir / "TESTX1_FLASH_BIOS_V9.99.iso.tmp").is_file()
    assert sorted(p.name for p in out_dir.glob("*.tmp")) == ["TESTX1_FLASH_BIOS_V9.99.iso.tmp"]


def test_unexpected_oserror_maps_to_exit_3(
    pkg: Path, out_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """m-7: 未预期 OSError 统一 print_error + 退出码 3, 不裸抛 traceback."""

    def boom(*_: object, **__: object) -> None:
        raise OSError("disk exploded")

    monkeypatch.setattr(cli, "discover", boom)
    assert cli.main([str(pkg), "-o", str(out_dir)]) == 3
    assert "未预期的 I/O 错误" in capsys.readouterr().err


def test_discard_cleanup_only_touches_this_run_names(
    pkg: Path, out_dir: Path, fail_verify_all: None
) -> None:
    """兜底清理不得误删输出目录里的既有旧产物."""
    out_dir.mkdir(parents=True)
    stale = out_dir / "OTHER_MODEL_FLASH_BIOS_V0.01.iso"
    stale.write_bytes(b"keep me")
    assert cli.main([str(pkg), "-o", str(out_dir)]) == 3
    assert stale.is_file()
    assert _leftovers(out_dir) == ("OTHER_MODEL_FLASH_BIOS_V0.01.iso",)


def test_validation_failure_keeps_zero_products(
    pkg: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """校验失败 (exit 2) 路径: 兜底清单为空, 不触碰输出目录."""

    def reject(*_: object, **__: object) -> None:
        raise ValidationError("校验失败", "指引")

    monkeypatch.setattr(cli, "validate", reject)
    assert cli.main([str(pkg), "-o", str(tmp_path / "never")]) == 2
    assert not (tmp_path / "never").exists()
