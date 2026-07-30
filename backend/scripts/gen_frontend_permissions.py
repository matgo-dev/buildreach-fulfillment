"""从后端权威源生成前端权限码文件(单一源头:后端 constants.py → 前端派生)。

用法(backend 目录下):uv run python scripts/gen_frontend_permissions.py
CI 在每次 PR 重跑本脚本并 `git diff --exit-code` 前端产物 —— 后端改了权限码但没重生成即报红。

不是「两份 + 一致性测试」:前端文件是本脚本的**派生产物**(文件头标注 DO NOT EDIT),
constants.py 是唯一著作源;CI 校验的是「派生是否最新」,非「两个独立源是否碰巧一致」。
"""
from __future__ import annotations

from pathlib import Path

from app.rbac.constants import PERMISSION_META, Permissions

_OUT = Path(__file__).resolve().parents[2] / "frontend" / "src" / "config" / "permission-matrix.ts"

_HEADER = """\
/**
 * AUTO-GENERATED —— 由 backend/scripts/gen_frontend_permissions.py 从
 * backend/app/rbac/constants.py 生成。请勿手改。
 *
 * 后端 constants.py 是权限码的唯一权威源;本文件与 DB permissions 表(启动 sync)同为其派生。
 * 新增/修改权限码:改后端 constants.py + PERMISSION_META,再重跑生成脚本(CI 会卡未重生成)。
 * 前端 <Can perm={Permissions.X}> 引用此处;真正的门控在后端每个端点。
 */
"""


def _entries() -> list[tuple[str, str, str]]:
    """(属性名, code, module),按 constants.py 定义顺序(vars 保序)。"""
    out: list[tuple[str, str, str]] = []
    for attr, code in vars(Permissions).items():
        if attr.startswith("__") or not isinstance(code, str):
            continue
        module = PERMISSION_META.get(code, {}).get("module", "")
        out.append((attr, code, module))
    return out


def render() -> str:
    lines = [_HEADER.rstrip(), "", "export const Permissions = {"]
    last_module = None
    for attr, code, module in _entries():
        if module != last_module:
            lines.append(f"  // {module}")
            last_module = module
        lines.append(f'  {attr}: "{code}",')
    lines.append("} as const;")
    lines.append("")
    lines.append("export type PermissionCode = (typeof Permissions)[keyof typeof Permissions];")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    _OUT.write_text(render(), encoding="utf-8")
    print(f"wrote {_OUT}")


if __name__ == "__main__":
    main()
