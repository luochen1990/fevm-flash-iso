# fevm-flash-iso 构建任务
# 约定: 先 `nix develop` 进入开发环境 (提供 python/ruff/mypy/pytest + mtools/dosfstools/xorriso)

default:
    @just --list

# 质量门禁: lint + 严格类型检查 + 测试与覆盖率 (>=85%)
check:
    ruff check .
    mypy --strict fevm_flash_iso tests
    pytest --cov=fevm_flash_iso --cov-report=term-missing --cov-fail-under=85

# 用合成 fixture 跑一次完整 CLI 构建 (临时目录, 不污染仓库)
build-demo:
    python3 scripts/build_demo.py

# 代码格式化与 lint 自动修复
fmt:
    ruff format .
    ruff check --fix .
