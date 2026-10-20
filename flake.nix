{
  description = "fevm-flash-iso: FEVM 固件包校验与 UEFI Shell 全自动刷写 ISO 构建器";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      pkgsFor = system: import nixpkgs { inherit system; };
    in
    {
      devShells = forAllSystems (
        system:
        let
          pkgs = pkgsFor system;
        in
        {
          default = pkgs.mkShell {
            # 职责边界: 提供可复现的开发/构建环境。
            # - python 侧工具链: python312 + ruff + mypy + pytest(+cov)
            # - 管线外部工具:   mtools(mcopy/mdir) + dosfstools(mkfs.vfat) + xorriso
            packages = [
              (pkgs.python312.withPackages (ps: with ps; [
                pytest
                pytest-cov
                mypy
              ]))
              pkgs.ruff
              pkgs.mtools
              pkgs.dosfstools
              pkgs.xorriso
              pkgs.just
            ];
          };
        }
      );
    };
}
