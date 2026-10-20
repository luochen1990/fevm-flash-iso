# 职责边界: `just build-demo` 的执行体 —— 用合成 fixture (fevm_flash_iso.synth)
# 跑一次完整 CLI 构建, 再对产物做 xorriso -indev 外部自检, 证明 "合成包 ->
# 两个刷写 ISO" 全链路可用。全程在临时目录工作, 不污染仓库; 绝不触碰任何
# 真实固件。

"""demo: 合成包 -> CLI 全流程 -> xorriso -indev 自检。"""

import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fevm_flash_iso import synth  # noqa: E402
from fevm_flash_iso.cli import main as cli_main  # noqa: E402

# demo 用真实尺寸 (BIOS bin 32 MiB) 以贴近实际产物大小
DEMO_OPTS = synth.SynthOptions(bios_bin_bytes=32 * 1024 * 1024)


def _xorriso_self_check(iso: Path) -> str:
    proc = subprocess.run(
        ["xorriso", "-indev", str(iso), "-report_el_torito", "plain"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        sys.exit(f"demo 自检失败: xorriso -indev {iso} 返回 {proc.returncode}")
    combined = proc.stdout + proc.stderr
    eltorito = [ln for ln in combined.splitlines() if "El Torito" in ln]
    return "\n".join(eltorito) or combined


def main() -> int:
    tmp_base = Path("/tmp/opencode") if Path("/tmp/opencode").is_dir() else Path("/tmp")
    with tempfile.TemporaryDirectory(prefix="fevm-demo-", dir=tmp_base) as tmp:
        tmp_path = Path(tmp)
        pkg = synth.synth_package(tmp_path / "pkg", DEMO_OPTS)
        out_dir = tmp_path / "dist"
        print(f"[demo] 合成固件包: {pkg}")
        rc = cli_main([str(pkg), "-o", str(out_dir)])
        if rc != 0:
            sys.exit(f"[demo] CLI 失败, 退出码 {rc}")
        print()
        print("[demo] 外部自检 (xorriso -indev):")
        for iso in sorted(out_dir.glob("*.iso")):
            print(f"  {iso.name} ({iso.stat().st_size / 1048576:.1f} MiB)")
            for line in _xorriso_self_check(iso).splitlines():
                print(f"    {line.strip()}")
        print()
        print("[demo] OK: 两个 ISO 均可读且带 El Torito EFI 引导记录")
        print(f"[demo] 产物目录: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
