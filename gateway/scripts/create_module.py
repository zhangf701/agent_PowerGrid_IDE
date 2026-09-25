"""`create-module` 脚手架 CLI（方案 v4 §六 / 模块化架构 §十）。

    # 在项目根下生成 modules/<id>/
    python gateway/scripts/create_module.py n1-ranking --name "N-1 排序研究"

    # 指定模块根目录
    python gateway/scripts/create_module.py my-topic --root ./modules

    # 覆盖已存在的目录
    python gateway/scripts/create_module.py my-topic --force

★ **默认生成 L0 声明式** —— 强制「先声明、后写码」的顺序，
  避免一上来就写 React 组件（多数选题根本不需要）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 让脚本能直接跑：把 src/ 加进 sys.path（gateway 通常已 editable 安装，这里只是兜底）
_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from powermcp_gateway.modules import (  # noqa: E402  —— 必须在 sys.path 调整之后
    KIND_ENGINEERING,
    KIND_RESEARCH,
    ModuleError,
    scaffold_module,
)


def _default_root() -> Path:
    """默认模块根 = 项目根下的 `modules/`（与 `modules.modules_root` 同口径）。"""
    return Path(__file__).resolve().parents[2] / "modules"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="create-module", description="生成一个选题模块骨架（默认 L0）"
    )
    ap.add_argument("module_id", help="模块 id：小写字母/数字/连字符，必须以字母开头")
    ap.add_argument("--name", default=None, help="显示名（默认与 id 相同）")
    ap.add_argument("--kind", choices=[KIND_RESEARCH, KIND_ENGINEERING],
                    default=KIND_RESEARCH, help="选题类别（默认 research）")
    ap.add_argument("--root", default=None, help="模块根目录（默认 <项目根>/modules）")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的目录")
    args = ap.parse_args(argv)

    root = Path(args.root) if args.root else _default_root()
    try:
        target = scaffold_module(root, args.module_id, name=args.name,
                                 kind=args.kind, force=args.force)
    except ModuleError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2

    print(f"✓ 已生成 L0 模块：{target}")
    print(f"  清单：{target / 'module.yaml'}")
    print()
    print("下一步：编辑 module.yaml 声明 tools / skills（L0 到此即可开工）；")
    print("        需要数据表时升到 L1（填 entities / result_tables 并给出 schema 文件）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
