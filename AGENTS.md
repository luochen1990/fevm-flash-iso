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
| `cmd.py` | subprocess 封装（300s 超时）+ 外部工具前置检查 | 业务逻辑 |
| `stage.py` | `CopyAction` 声明式动作表 -> stage 源树；期望路径清单 | 调外部命令 |
| `fatimg.py` | FAT16 镜像构建（truncate/mkfs.vfat/mcopy） | 改参数语义 |
| `iso.py` | xorriso 组装（临时名）+ 产物自检（内嵌副本哈希/Platform Id/mdir） | 校验输入包 |
| `report.py` | 全部用户可见文本 | 业务逻辑 |
| `cli.py` | 参数集中预处理 + 管线编排 + 原子发布与失败兜底清理 + 退出码契约 | 散落的路径解析 |
| `synth.py` | 合成固件包生成（仅测试/demo） | 进刷写管线；包含真实固件 |

## 校验规则清单（fail fast，失败即退出码 2）

| # | 规则 | 实现位置 |
| --- | --- | --- |
| 1 | 恰好一个 BIOS 目录（`*.bin`+`Tools/AfuEfix64.efi`+`Tools/nFlash.nsh`）与恰好一个 EC 目录（`EC_*.bin`+`ifu.efi`+`FEC64.NSH`），按内容识别，支持显式覆盖；歧义判定带完整目录路径，且先做内容指纹预筛（无指纹的目录不参与另一类的 bin 歧义判定） | `discover.py` |
| 2 | 所有被消费的 `.efi` 是 PE/COFF 且 Machine=0x8664，OptionalHeader Magic=0x20B（PE32+），SizeOfHeaders ≤ 文件长度（截断/伪体拒绝） | `pecoff.py`（validate 调用，含 Shell.efi） |
| 3 | `FEC64.NSH` 双通道交叉校验：**至少一条非注释 `ifu <name>` 行**（完全没有 → 硬失败，防"静默无操作" EC 盘）；严格通道——每条 `ifu <name>` 行引用的文件必须存在于目录；宽松通道——实际 bin 名 ∈ 全文 EC bin token 集合（兼容厂商注释头引用旧名形态） | `validate._check_fec_ref` |
| 4 | `nFlash.nsh` 内容引用 `.\Tools\AfuEfix64.efi` | `validate._check_nflash_ref` |
| 5 | BIOS bin ≥ 8 MiB（实测 32 MiB）且 < FAT 容量 × 0.9（实测 64 MiB）；EC bin ∈ {64K,128K,256K,512K}（实测 128K） | `validate._check_bin_sizes`（容量由 cli 从 `BUILD_SPECS` 注入） |
| 6 | 机型/BIOS 版本/内嵌 EC 版本/EC 包版本解析展示 + 软一致性（release 尾段比较，不一致仅 warning）；BIOS 版本字段多候选时**硬失败**（不错标 ISO 名） | `filenames.py` + `validate.py` |
| 7 | `ChecksumF.txt` 存在则解析 `[bin] checksum : 8hex` 并提示"供人工比对"（ITE 私有算法未知，不硬校验）；文件随 EC 盘分发 | `validate._checksum_info` + `stage.py` |
| 8 | 产物自检（对象 = **成品 ISO 的内嵌副本**）：`xorriso -indev` 可读 + El Torito Platform Id 行为 EFI/UEFI 且引导镜像为 `/efi.img`（正则解析，非子串）；`-osirrox` 抽回内嵌 `efi.img` 与源镜像 SHA-256 比对；对内嵌副本逐路径 `mdir`。产物**原子发布**：先写 `<名>.iso.tmp`，自检通过后 `os.replace` 到最终名；构建失败时清理本次运行全部 `.iso/.tmp` 残留并报告作废清单 | `iso.py` + `cli.py` |

每条失败信息都含「出了什么事 + 修复指引」两部分（`ValidationError.what/hint`）。

## 退出码契约

| 码 | 含义 |
| --- | --- |
| 0 | 成功：两个 ISO 均构建并通过自检后原子发布 |
| 2 | 输入包/环境校验失败（ValidationError：结构/内容/工具缺失） |
| 3 | 构建或自检失败（BuildError：外部工具失败/超时/自检不过/原子发布兜底清理），**含未预期的 I/O 错误（OSError 与子进程解码异常也归 3，不裸抛 traceback）** |

## 版本解析规约（正则不写死整串，只提取关键字段）

- BIOS bin：`(?<!EC_)V(\d+\.\d+)` 提取 BIOS 版本字段——负向后视排除
  `EC_V` 前缀，防止把内嵌 EC 版本误读成 BIOS 版本；**过度排除是失败
  安全的**：若机型名/字段恰好使全部 `V` 字段都被排除（如 `XXXEC_V1.06`
  形），解析得到空集合 → 硬失败，绝不静默猜。
- BIOS 版本**唯一性**：全部非 EC `V` 字段的取值集合必须恰有一个元素；
  多个互不相同的候选 → 硬失败（防 ISO 文件名标错版本）；重复出现同一
  值不算歧义。
- 内嵌 EC 版本：`EC_V(\d+(?:\.\d+)+)`——显式数字段结构，不吃尾点
  （`EC_V0.1.29_20260720.bin` → `0.1.29`，无尾点假警告）。
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
   命中」结构（`if exist fs%z:\<probe> then ... endif`）。
3. **fs 设备号不固定**——实测 Ventoy 场景 ISO 挂在 FS1；必须用
   `for %z run (0 9)` 探测循环。
4. **for 循环变量只能用单个 ASCII 字母**（EDK2 `For.c` 强制校验
   `%<字母>`，多字符名直接报 Invalid variable 被拒），且必须与厂商脚本
   错开——厂商 `nFlash.nsh` 用 `for %a in *bin`，本模板用 **`%z`**
   （同名会被内层脚本覆盖）。
5. 行尾 CRLF，与厂商脚本一致。
6. 语法白名单：`@echo -off` / `echo` / `stall <微秒>` /
   `for %z run (0 9)`…`endfor` / `if exist <path> then`…`endif` /
   `fs%z:` / `cd` / 脚本调用。
7. 布局常量（`0_Afu_Flash`、`EC`、`EFI/BOOT/BOOTX64.EFI`、`startup.nsh`）
   集中在 `model.BUILD_SPECS`，与 `stage.py` 布局、`texts.py` 探测路径
   同源——改布局只改 model 一处。

## 构建管线命令（2026-10 实机验证，照抄勿改参数语义）

```console
$ truncate -s <64|8>M efi.img
$ mkfs.vfat -F 16 -s <4|1> -n <FEVMBIOS|FEVMEC> efi.img   # -s 显式几何, 见下
$ mcopy -i efi.img -s <stage 各顶层条目> ::
$ xorriso -as mkisofs -quiet -volid <VOLID> -J -joliet-long \
    -eltorito-alt-boot -e efi.img -no-emul-boot \
    -append_partition 2 0xEF efi.img -o <OUT>.iso.tmp isoroot/
$ # 自检通过后: os.replace <OUT>.iso.tmp <OUT>.iso (原子发布, M-1)
```

- xorriso 以 `isoroot/` 为工作目录执行（源参数 `.`），`efi.img` 用裸相对
  路径同时喂给 `-e`（要求镜像在源目录树内——实测踩坑）与
  `-append_partition`（从磁盘 cwd 读）。
- `-s` 显式扇区/簇：dosfstools 4.2 的自动簇适配在 8 MiB 上选不出合法
  FAT16 参数（实测报 "too small or a too large filesystem"）；8 MiB 用
  `-s 1`（≈16K 簇），64 MiB 用 `-s 4`（≈32K 簇），跨版本可复现。
- 外部命令统一 300 秒超时（`cmd.COMMAND_TIMEOUT_SECONDS`），超时转
  BuildError（防工具卡死挂起 CLI）。
- 构建前扫描输出目录既有 `*.iso`（旧版本产物）与孤儿 `*.iso.tmp`（中断/
  断电残留）并分别打印提醒（防 Ventoy 中新旧拿混 / 防误用残缺文件）；
  同名重建不告警（将被原子替换）；提醒不代删，由用户手动清理。

ISO 内布局：

- BIOS 盘：`EFI/BOOT/BOOTX64.EFI`、`startup.nsh`、`README.txt`、
  `0_Afu_Flash/{*.bin, Tools/{AfuEfix64.efi, nFlash.nsh}}`（保持厂商脚本的
  相对路径约定：nFlash.nsh 在当前目录找 `*.bin`、调 `.\Tools\AfuEfix64.efi`）
- EC 盘：`EFI/BOOT/BOOTX64.EFI`、`startup.nsh`、`README.txt`、
  `EC/{EC bin, ifu.efi, FEC64.NSH, uiset.ini}`（FEC64.NSH 依赖当前目录的
  ifu 和 bin）；包内存在 `ChecksumF.txt` 时一并放入 `EC/`（随盘供人工比对）

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

## 固件分支与自动发布（`firmware/**` + release.yml）

master **永不包含真实固件**；固件存放在独立分支，CI 自动构建并发布：

- 分支命名：`firmware/<机型小写>`（如 `firmware/faex1`），**基于 master 创建**，在其上新增三样东西，其余文件不动：
  - `pkg/`：解压后的官方固件包原样目录（pkg/ 下直接是 BIOS/EC 两个目录）；
  - `PROVENANCE.md`：人写的来源记录（原始下载地址、下载日期、BIOS/EC 版本号、备注），发布时全文进 release notes；
  - `sha256.txt`：`(cd pkg && find . -type f | sort | xargs sha256sum) > sha256.txt` 生成，CI 用 `sha256sum --check` fail fast 校验。
- **为什么必须基于 master**：`on: push` 只执行*被 push 分支上*的 workflow 文件，孤立分支上没有 `.github/workflows/release.yml`，推送不会触发发布。
- **同步 master 用 merge 不用 rebase**：rebase 改写历史 → push 需 force；force-push 禁止（release tag 钉在固件分支 commit 上，历史必须稳定）。merge 无冲突风险（`pkg/`、`PROVENANCE.md`、`sha256.txt` 与 master 路径永不相交）。
- **固件分支永不并回 master**。

发布行为（release.yml，push 到 `firmware/**` 自动触发）：

sha256 校验 → CLI 构建 + 产物自检 → 从 ISO 文件名推导 tag
`<机型小写>-bios<BIOS版本>-ec<EC版本>`（如 `faex1-bios1.06-ec9.4.0.1.29`）→
上传两个 ISO + `SHA256SUMS` 到该 tag 的 release（同版本重推 = clobber 覆盖更新资产与 notes）。

维护流程：

```console
# 初始化新机型固件分支（每机型一次）:
$ git checkout -b firmware/faex1 origin/master
$ mkdir pkg && cp -r <解压后的固件包>/* pkg/
$ (cd pkg && find . -type f | sort | xargs sha256sum) > sha256.txt
$ $EDITOR PROVENANCE.md      # 下载地址/日期/版本/备注
$ git add pkg sha256.txt PROVENANCE.md
$ git commit -m "firmware: FAEX1 BIOS V1.06 + EC V9.4.0.1.29"
$ git push -u origin firmware/faex1   # push 即触发自动发布

# 固件版本更新:
$ git checkout firmware/faex1
$ git fetch origin && git merge origin/master   # 先同步 master (必须, merge 非 rebase)
$ rm -rf pkg && mkdir pkg && cp -r <新包>/* pkg/
$ (cd pkg && find . -type f | sort | xargs sha256sum) > sha256.txt
$ $EDITOR PROVENANCE.md                      # 更新版本与来源
$ git add -A && git commit -m "firmware: FAEX1 BIOS V1.07 + EC ..."   # msg 注明版本号
$ git push
```

注：GitHub 单文件硬限 100 MiB（BIOS bin 实测 32 MiB，安全）；固件分支对
public 仓库可见，含厂商专有工具与固件镜像的再分发（FEVM 官方本就免费公开
分发，风险自担，PROVENANCE 保留原始出处）。

## 开发循环

```console
$ nix develop          # 进入可复现环境
$ just check           # lint + 类型 + 测试(覆盖率门禁)
$ just build-demo      # 合成包 -> 两个 ISO 的端到端演示 (临时目录)
$ just fmt             # ruff format + autofix
```

CI（ci.yml）：push/PR 到 master 自动执行 `nix develop -c just check` +
`just build-demo`，与本地质量门禁同源。

提交纪律：按逻辑分 commit（骨架/实现/测试/文档），msg 一行简洁；
清理代码的 commit 必须在 msg 里留下可搜索的关键词。
