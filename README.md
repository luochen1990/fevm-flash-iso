# fevm-flash-iso

FEVM（AMD Strix Halo 迷你主机）官方固件包只提供 Windows 刷写工具；
Linux 用户此前只能借一台 Windows 机器刷 BIOS 和 EC。本项目把一条
**已在实机上验证成功的纯 UEFI Shell 刷写路线**固化成工具：

> 输入 FEVM 固件包目录 → 逐项校验 → 产出两个全自动刷写 ISO（BIOS 盘 / EC 盘），
> 拷进 Ventoy U 盘即可在目标机上免 Windows 刷写。

刷写动作本身由厂商原版工具完成（AMI AFU `AfuEfix64.efi` + `nFlash.nsh`
刷 BIOS，ITE `ifu.efi` + `FEC64.NSH` 刷 EC），本工具只做校验、组装与
自检，不改动任何厂商脚本参数。

## 特性

- **零 Windows**：整条链路 = UEFI Shell 2.2 + 厂商 EFI 工具 + FAT 引导镜像。
- **fail fast 校验**：结构识别（按内容指纹，不依赖目录名）、EFI 文件
  PE32+/x64 健全性校验、厂商脚本与固件文件名交叉校验、固件尺寸校验、
  版本解析与软一致性提醒——任何硬校验不过立即终止并给出修复指引，
  绝不产出可疑刷写盘。
- **产物自检 + 原子发布**：每个 ISO 先以临时名构建，用 `xorriso` 验证
  可读、El Torito EFI 引导记录、内嵌引导镜像与源镜像逐字节一致，全部
  通过后才改名为正式产物；构建失败自动清理本次全部半成品，输出目录
  绝不残留以正式名示人的坏 ISO。检测到旧版本产物时会提醒手动清理。
- **全自动刷写体验**：ISO 引导进 UEFI Shell 后，`startup.nsh` 探测
  fs0..fs9 找到 payload，5 秒倒计时后自动执行厂商脚本。
- **绝不含真实固件**：仓库与测试只包含程序合成的 fixture；内置的
  UEFI Shell（edk2，BSD-2-Patent）可再分发，来源见
  `fevm_flash_iso/assets/SHELL_SOURCE.md`。

## 安装

NixOS / 任意有 Nix 的 Linux：

```console
$ git clone <repo-url> fevm-flash-iso && cd fevm-flash-iso
$ nix develop        # python3.12 + ruff + mypy + pytest + mtools + dosfstools + xorriso
```

非 Nix 环境需自行准备：python ≥ 3.12、mtools（`mcopy`/`mdir`）、
dosfstools（`mkfs.vfat`）、xorriso。

## 用法

```console
$ python3 -m fevm_flash_iso <固件包根目录> [选项]

选项:
  -o, --out-dir PATH   输出目录 (默认 <包根>/dist)
  --shell-efi PATH     覆盖内置 UEFI Shell (edk2 Shell x64)
  --bios-dir PATH      显式指定 BIOS 目录 (跳过自动识别)
  --ec-dir PATH        显式指定 EC 目录 (跳过自动识别)
  --keep-stage         保留 stage/isoroot 中间目录 (调试用)
```

（以 `pip install` 方式安装本包后，也可直接使用 `fevm-flash-iso` 入口。）

预期输入是解压后的 FEVM 官方固件包（目录名可变，工具按内容识别）：

```
<包根>/
  <机型>_BIOS/        # *.bin (32 MiB) + Tools/AfuEfix64.efi + Tools/nFlash.nsh
  <机型>EC/           # EC_*.bin (128 KiB) + ifu.efi + FEC64.NSH [+ uiset.ini, ChecksumF.txt]
```

运行成功后在输出目录得到：

- `<机型>_FLASH_BIOS_V<版本>.iso` —— BIOS 刷写盘
- `<机型>_FLASH_EC_V<版本>.iso` —— EC 刷写盘

同时终端打印：机型/版本摘要表、每个 ISO 的 FAT 镜像内容清单、下一步
操作提示。

试运行（合成数据，不碰真实固件）：

```console
$ just build-demo
```

## 刷写步骤（输出 ISO 的使用方式）

1. 把两个 ISO 拷入 Ventoy U 盘。
2. 目标机开机按 **F7** 进入启动菜单，选择对应 ISO。
3. UEFI Shell 启动后 **5 秒倒计时**结束即自动开始刷写。
4. **BIOS 盘**：刷写工具要求确认时按 **y**。
5. **EC 盘**：刷写完成后**自动关机**；必须**拔电源等 10 秒**再通电。

## 预构建 ISO（Releases）

不想自己构建？每个机型的固件存放在独立的 `firmware/<机型>` 分支，push
后 CI 自动完成 sha256 校验 → 构建 → 产物自检 → 发布：前往仓库
**Releases** 页下载两个 ISO 与 `SHA256SUMS`（下载后请核对校验和）。
release notes 附固件原始来源与刷写安全提示。维护者流程见 `AGENTS.md`。

## 限制

- 仅实测过 **FEVM FAEX1**（AMD Strix Halo）固件包格式；其他机型的命名
  规约或厂商脚本若不同，需先适配校验规则。
- `ChecksumF.txt` 的校验算法是 ITE 私有，本工具只解析展示、**供人工
  比对**，不做硬校验。
- Ventoy 引导已实测验证；其他引导器未逐一验证（UEFI 光盘引导是标准
  路径，预期可用）。
- 本工具不改动厂商刷写脚本的任何参数；刷写风险与厂商 Windows 工具
  相同，请在确认固件版本无误后再刷。

## 许可

- 本项目代码：MIT。
- 内置 `fevm_flash_iso/assets/Shell.efi`：EDK2 UEFI Shell，BSD-2-Clause-Patent，
  来源与提取命令见 `fevm_flash_iso/assets/SHELL_SOURCE.md`。
