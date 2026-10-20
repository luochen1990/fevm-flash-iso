# assets/Shell.efi 来源记录

本目录下的 `Shell.efi` 是构建刷写 ISO 时默认使用的 UEFI Shell
(EDK2 UEFI Shell 2.2, X64), 作为 FAT 引导镜像内的
`EFI/BOOT/BOOTX64.EFI` 落盘。可用 CLI 参数 `--shell-efi <PATH>` 覆盖。

## 来源

- 上游项目: <https://github.com/pbatard/UEFI-Shell> (Pete Batard 维护的
  预编译 UEFI Shell 发行版)
- 下载文件: <https://github.com/pbatard/UEFI-Shell/releases/download/23H1/UEFI-Shell-2.2-23H1-RELEASE.iso>
- 版本: UEFI Shell 2.2, 23H1 release (2023-06-06)
- 提取对象: ISO 内 `efi/boot/bootx64.efi` (重命名为 `Shell.efi`)

## 提取命令

```console
$ curl -fL -o UEFI-Shell-2.2-23H1-RELEASE.iso \
    https://github.com/pbatard/UEFI-Shell/releases/download/23H1/UEFI-Shell-2.2-23H1-RELEASE.iso
$ xorriso -osirrox on -indev UEFI-Shell-2.2-23H1-RELEASE.iso \
    -extract /efi/boot/bootx64.efi Shell.efi
```

## 校验

- SHA-256 (Shell.efi): `07b23aa4ff3a8bac03533762663e3c2f516b42faa167f390f172d88af4042fe2`
- 大小: 1053248 字节
- PE/COFF: MZ / PE\0\0 签名合法, Machine = 0x8664 (AMD64) —— 与仓库内
  `fevm_flash_iso/pecoff.py` 的校验逻辑一致, CLI 每次构建前都会自检。

## 许可

UEFI Shell 是 EDK2 (TianoCore) 的组成部分, 以 **BSD-2-Clause-Patent**
许可证发布, 允许再分发与二进制打包, 因此可以随本仓库分发。许可证全文:
<https://github.com/tianocore/edk2/blob/master/License.txt>
