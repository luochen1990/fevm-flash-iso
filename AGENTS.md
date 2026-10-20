# AGENTS.md — fevm-flash-iso 维护者手册

本文件写给维护者（How）；使用者文档见 `README.md`（What/Why）。

## 项目阶段与兼容性立场

POC → MVP 过渡期，自用/亲友范围。**不处理任何兼容性负担**：CLI 参数、
输出布局、内部 API 均可随需求自由重构，以代码库简洁为第一优先。

## 术语表

| 术语 | 含义 |
| --- | --- |
| BIOS | 主板固件（本机为 AMI UEFI BIOS，32 MiB 镜像，`AfuEfix64.efi` 以 `/CAPSULE` 模式刷写） |
| EC | Embedded Controller（本机为 ITE IT5570E，128 KiB 镜像，`ifu.efi` 刷写） |
| Capsule | UEFI 固件胶囊更新模式，AMI AFU 的刷写参数之一（厂商脚本自带，勿改） |
| AFU | AMI Aptio Flash Update，`AfuEfix64.efi` 的 UEFI 版刷写工具 |
| IFU | ITE Firmware Update，`ifu.efi`，ITE EC 刷写工具 |
| UEFI Shell | EDK2 的 UEFI Shell 2.2（`assets/Shell.efi`），ISO 引导后的命令环境，自动执行 FAT 根目录的 `startup.nsh` |
| startup.nsh | UEFI Shell 启动脚本（我们生成，负责找 payload 并调厂商脚本） |
| NSH | UEFI Shell 脚本后缀；厂商脚本 `nFlash.nsh`（BIOS）/ `FEC64.NSH`（EC） |
| El Torito | ISO9660 的启动记录规范；EFI 引导记录指向 `efi.img` |
| Ventoy | U 盘多 ISO 引导工具；实测场景中 ISO 被挂载为 FS1（设备号不固定） |
| FAT 引导镜像 | `efi.img`，FAT16 文件系统镜像；UEFI 固件从 El Torito 记录引导它 |
| stage | 构建 ISO 时的中间源目录（FAT 镜像内容），`--keep-stage` 可保留 |
| 合成 fixture | `fevm_flash_iso/synth.py` 程序生成的假固件包，测试/演示专用 |

## 核心抽象与数据流

```
CLI(argv)
  └─> discover    结构层: 包根 -> PackageLayout (BIOS/EC 目录, 按内容指纹)
      └─> validate 内容层: PackageLayout -> FirmwareSummary (版本/尺寸/交叉引用/警告)
          └─> shell   UEFI Shell 定位+PE 自检 -> Path
              └─> 对每个 FlashTarget(BIOS/EC):
                    stage   动作表 CopyAction[] -> stage/ 源树
                    fatimg  stage/ -> efi.img (truncate/mkfs.vfat/mcopy)
                    iso     isoroot/ -> .iso (xorriso -as mkisofs) + 自检(校验#8)
                    report  摘要表/内容清单/下一步提示
```

不可变数据（`dataclass(frozen=True)`）贯穿全程；`Enum` 表达 `FlashTarget`；
所有路径解析与默认值收敛在 `cli.parse_args`（集中式预处理），下游模块
拿到的都是绝对路径与合规数据，不做防御式参数检查。

## 模块职责边界

| 模块 | 职责 | 禁止 |
| --- | --- | --- |
| `model.py` | 共享类型/常量/每个目标的 `BuildSpec`（实测参数，SSOT） | 任何 IO |
| `filenames.py` | 文件名/版本/checksum 行解析（纯函数） | 读文件、做校验决策 |
| `pecoff.py` | PE/COFF 头解析与 x64 EFI 自检 | 解析节表/证书 |
| `discover.py` | 结构层校验 #1（内容指纹识别 + `--bios-dir/--ec-dir`） | 读文件内容做内容层判断 |
| `validate.py` | 内容层校验 #2–#7，产出 `FirmwareSummary` | 修改任何文件 |
| `shell.py` | UEFI Shell 定位（覆盖参数/内置资产）+ PE 自检 | 构建镜像 |
| `texts.py` | `startup.nsh`/`README.txt` 生成（纯函数，EDK2 坑集中地） | 执行 IO |
| `cmd.py` | subprocess 封装 + 外部工具前置检查 | 业务逻辑 |
| `stage.py` | `CopyAction` 声明式动作表 -> stage 源树；期望路径清单 | 调外部命令 |
| `fatimg.py` | FAT16 镜像构建（truncate/mkfs.vfat/mcopy） | 改参数语义 |
| `iso.py` | xorriso 组装 + 产物自检（#8）+ FAT 镜像清单 | 校验输入包 |
| `report.py` | 全部用户可见文本 | 业务逻辑 |
| `cli.py` | 参数集中预处理 + 管线编排 + 退出码 | 散落的路径解析 |
| `synth.py` | 合成固件包生成（仅测试/demo） | 进刷写管线；包含真实固件 |

## 校验规则清单（fail fast，失败即退出码 2）

| # | 规则 | 实现位置 |
| --- | --- | --- |
| 1 | 恰好一个 BIOS 目录（`*.bin`+`Tools/AfuEfix64.efi`+`Tools/nFlash.nsh`）与恰好一个 EC 目录（`EC_*.bin`+`ifu.efi`+`FEC64.NSH`），按内容识别，支持显式覆盖 | `discover.py` |
| 2 | 所有被消费的 `.efi` 是 PE/COFF 且 Machine=0x8664 | `pecoff.py`（validate 调用，含 Shell.efi） |
| 3 | `FEC64.NSH` 引用的 bin 名 ∈ 目录内实际 bin 名（按 `EC_...V...F.bin` token 集合；脚本注释行允许有旧名） | `validate._check_fec_ref` |
| 4 | `nFlash.nsh` 内容引用 `.\Tools\AfuEfix64.efi` | `validate._check_nflash_ref` |
| 5 | BIOS bin ≥ 8 MiB（实测 32 MiB）；EC bin ∈ {64K,128K,256K,512K}（实测 128K） | `validate._check_bin_sizes` |
| 6 | 机型/BIOS 版本/内嵌 EC 版本/EC 包版本解析展示 + 软一致性（release 尾段比较，不一致仅 warning） | `filenames.py` + `validate.py` |
| 7 | `ChecksumF.txt` 存在则解析 `[bin] checksum : 8hex` 并提示"供人工比对"（ITE 私有算法未知，不硬校验） | `validate._checksum_info` |
| 8 | 产物自检：`xorriso -indev` 可读 + El Torito EFI 记录（`/efi.img`）+ `mdir` 逐路径检查 FAT 镜像 | `iso.verify_iso` |

每条失败信息都含「出了什么事 + 修复指引」两部分（`ValidationError.what/hint`）。

## 版本解析规约（正则不写死整串，只提取关键字段）

- BIOS bin：`V(\d+\.\d+)` 取首个匹配为 BIOS 版本；`EC_V([\d.]+)` 为内嵌 EC 版本
  （如 `..._S112_V1.06_..._EC_V0.1.29_20260720.bin`）。
- EC bin：`EC_(\w+?)_V(\d+(?:_\d+)+)(F?)\.bin`，下划线串转点分
  （`EC_FEVM_V9_4_0_1_29F.bin` → `9.4.0.1.29` + F 后缀）。
- 机型：目录名首个 `_` 前的 token（BIOS 目录优先，EC 目录回退；不一致告警）。
- EC 版本一致性 = 比较两个版本串的**最后两个数字段**（release 尾段）：
  BIOS 内嵌 `0.1.29` vs EC 包 `9.4.0.1.29` → `1.29 == 1.29` → 一致。
  前三段是 ITE 工程版本，不参与比较。

## startup.nsh 的坑（实测踩过，改模板前必读）

1. **echo 内容绝不能以 `-`、`=`、`/` 开头**——EDK2 echo 把首 token 当 flag
   解析，报 `echo: Unknown flag`。提示文本字母数字开头，分隔线用 `xxx…`。
2. **不要用 goto 跳出 for 循环**——跨块 goto 语义不稳；用「目标路径唯一
   命中」结构（`if exist fs%a:\<probe> then ... endif`）。
3. **fs 设备号不固定**——实测 Ventoy 场景 ISO 挂在 FS1；必须用
   `for %a run (0 9)` 探测循环。
4. 行尾 CRLF，与厂商脚本一致。
5. 语法白名单：`@echo -off` / `echo` / `stall <微秒>` /
   `for %a run (0 9)`…`endfor` / `if exist <path> then`…`endif` /
   `fs%a:` / `cd` / 脚本调用。
6. 布局常量（`0_Afu_Flash`、`EC`、`EFI/BOOT/BOOTX64.EFI`、`startup.nsh`）
   集中在 `model.BUILD_SPECS`，与 `stage.py` 布局、`texts.py` 探测路径
   同源——改布局只改 model 一处。

## 构建管线命令（2026-10 实机验证，照抄勿改参数语义）

```console
$ truncate -s <64|8>M efi.img
$ mkfs.vfat -F 16 -s <4|1> -n <FEVMBIOS|FEVMEC> efi.img   # -s 显式几何, 见下
$ mcopy -i efi.img -s <stage 各顶层条目> ::
$ xorriso -as mkisofs -quiet -volid <VOLID> -J -joliet-long \
    -eltorito-alt-boot -e efi.img -no-emul-boot \
    -append_partition 2 0xEF efi.img -o <OUT>.iso isoroot/
```

- xorriso 以 `isoroot/` 为工作目录执行（源参数 `.`），`efi.img` 用裸相对
  路径同时喂给 `-e`（要求镜像在源目录树内——实测踩坑）与
  `-append_partition`（从磁盘 cwd 读）。
- `-s` 显式扇区/簇：dosfstools 4.2 的自动簇适配在 8 MiB 上选不出合法
  FAT16 参数（实测报 "too small or a too large filesystem"）；8 MiB 用
  `-s 1`（≈16K 簇），64 MiB 用 `-s 4`（≈32K 簇），跨版本可复现。

ISO 内布局：

- BIOS 盘：`EFI/BOOT/BOOTX64.EFI`、`startup.nsh`、`README.txt`、
  `0_Afu_Flash/{*.bin, Tools/{AfuEfix64.efi, nFlash.nsh}}`（保持厂商脚本的
  相对路径约定：nFlash.nsh 在当前目录找 `*.bin`、调 `.\Tools\AfuEfix64.efi`）
- EC 盘：`EFI/BOOT/BOOTX64.EFI`、`startup.nsh`、`README.txt`、
  `EC/{EC bin, ifu.efi, FEC64.NSH, uiset.ini}`（FEC64.NSH 依赖当前目录的
  ifu 和 bin）

## UEFI Shell 资产

`fevm_flash_iso/assets/Shell.efi` = edk2 UEFI Shell 2.2（23H1 release，
pbatard/UEFI-Shell 预编译 ISO 内 `efi/boot/bootx64.efi`，xorriso osirrox
提取，BSD-2-Patent 可再分发）。来源/校验和/提取命令见
`fevm_flash_iso/assets/SHELL_SOURCE.md`。入库前已用 `pecoff.py` 自检；
CLI 每次构建前还会再自检一次。

## 测试约定

- **只用合成数据**：`conftest.py` 的 fixture 全部来自 `synth.py`（随机字节
  bin + 手工 PE 头假 efi + 自写脚本），**绝不读取** `~/Downloads` 下的真实
  固件；bin 内容以 `SYNTHETIC-...` 标记开头。
- golden 测试：合法合成包 → CLI 全流程 → 两个 ISO（`tests/test_golden.py`，
  需外部工具，缺失时 skip）。
- 变异参数化：删文件/错文件名/坏 MZ 头/错尺寸/NSH 引用不一致 →
  退出码 2 + 错误信息含修复指引（`tests/test_mutations.py`）。
- 纯函数层（filenames/pecoff/texts）不依赖外部工具，随时可跑。
- 质量门禁：`just check` = ruff + `mypy --strict` + pytest 覆盖率 ≥ 85%。

## 开发循环

```console
$ nix develop          # 进入可复现环境
$ just check           # lint + 类型 + 测试(覆盖率门禁)
$ just build-demo      # 合成包 -> 两个 ISO 的端到端演示 (临时目录)
$ just fmt             # ruff format + autofix
```

提交纪律：按逻辑分 commit（骨架/实现/测试/文档），msg 一行简洁；
清理代码的 commit 必须在 msg 里留下可搜索的关键词。
