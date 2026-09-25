#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 `design/tokens.json` 生成前端可用的产物（设计系统落地）。

生成两件：

1. `frontend/src/styles/tokens.css` —— 两套 CSS 变量
   （`:root, [data-theme="light"]` 与 `[data-theme="dark"]`）
2. `frontend/src/design/tokens.generated.js` —— 状态签名等**数据** + Tailwind 主题扩展

★★ **单一真源**：本脚本**只读** `design/tokens.json`，**绝不反向写入**。
   产物顶部带「勿手改」标记；`--check` 模式是**护栏** ——
   产物与真源不一致时以退出码 1 报错（可放进 CI / pre-commit）。

★ 命名规则与 `tools/check_design_tokens.py` **保持一致**（同一份映射表的两处消费者）：
   语义层 `--c-{路径}`（`categorical` → `cat`）；原始层按组加前缀。
   ⚠️ 两处若漂移，生成的 CSS 会与文档校验的令牌名对不上 —— 这是最该防的失败模式。

用法：
    python tools/build_design_tokens.py            # 生成
    python tools/build_design_tokens.py --check    # 只校验是否已同步（不写盘）

退出码：0 = 成功/已同步；1 = 失败/产物漂移。
"""

import json
import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

ROOT = Path(__file__).resolve().parent.parent
TOKENS_JSON = ROOT / "design" / "tokens.json"
OUT_CSS = ROOT / "frontend" / "src" / "styles" / "tokens.css"
OUT_JS = ROOT / "frontend" / "src" / "design" / "tokens.generated.js"
OUT_PREVIEW = ROOT / "frontend" / "preview.html"

BANNER = "由 tools/build_design_tokens.py 从 design/tokens.json 生成 —— 勿手改"

#: 与 check_design_tokens.py 的 SEGMENT_RENAME 保持一致
SEGMENT_RENAME = {"categorical": "cat"}

#: 原始层 → CSS 变量前缀（与 check_design_tokens.py 的 group_map 一致）
PRIMITIVE_GROUPS = (
    ("space", "--p-space-"),
    ("radius", "--p-radius-"),
    ("fontSize", "--p-font-size-"),
    ("borderWidth", "--p-border-"),
    ("fontFamily", "--p-font-"),
    ("shadow", "--p-shadow-"),
)

#: 只在 JS 产物里导出、不进 CSS 的数据段
DATA_SECTIONS = (
    "stateSignature",
    "unknownReason",
    "contractTypes",
    "identifierConvention",
    "engineChartColor",
)

_ALIAS = re.compile(r"^\{([^}]+)\}$")


def die(msg: str) -> None:
    print(f"\n[FAIL] {msg}")
    sys.exit(1)


def load() -> dict:
    if not TOKENS_JSON.exists():
        die(f"令牌真源不存在：{TOKENS_JSON}")
    try:
        return json.loads(TOKENS_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"tokens.json 不是合法 JSON：line {e.lineno} col {e.colno} — {e.msg}")


def resolve(value, root, seen=()):
    """解析 `{a.b.c}` 形式的别名引用（与 check_design_tokens.py 同语义）。"""
    if not isinstance(value, str):
        return value
    m = _ALIAS.match(value.strip())
    if not m:
        return value
    path = m.group(1)
    if path in seen:
        die(f"别名循环引用：{' -> '.join(seen + (path,))}")
    node = root
    for seg in path.split("."):
        if not isinstance(node, dict) or seg not in node:
            die(f"别名无法解析：{{{path}}}（在 {seg} 处断掉）")
        node = node[seg]
    return resolve(node.get("$value") if isinstance(node, dict) else node,
                   root, seen + (path,))


def leaves(node, prefix=()):
    """深度优先遍历，产出 `(路径元组, 叶子)`；叶子是含 `$value` 的 dict。"""
    if not isinstance(node, dict):
        return
    if "$value" in node:
        yield prefix, node
        return
    for key, child in node.items():
        if key.startswith("$"):
            continue
        yield from leaves(child, prefix + (key,))


# ---------------------------------------------------------------- CSS


def _semantic_names(root: dict):
    """语义层令牌名 → (浅色值, 深色值)。两主题必须成对。"""
    light = root.get("semantic", {}).get("light", {})
    dark = root.get("semantic", {}).get("dark", {})

    def collect(node, prefix=()):
        out = {}
        for path, leaf in leaves(node):
            name = "--c-" + "-".join(
                SEGMENT_RENAME.get(s, s) for s in prefix + path
            )
            out[name] = leaf["$value"]
        return out

    lo, hi = collect(light), collect(dark)
    only_light = sorted(set(lo) - set(hi))
    only_dark = sorted(set(hi) - set(lo))
    if only_light or only_dark:
        die(
            "语义层未在浅/深两主题中成对定义："
            f"仅浅色 {only_light}；仅深色 {only_dark}"
        )
    return lo, hi


def _primitive_names(root: dict):
    """与主题无关的原始层令牌名 → 值。**颜色不进 CSS**（必须走语义层）。"""
    prim = root.get("primitive", {})
    out: dict[str, str] = {}
    for group, prefix in PRIMITIVE_GROUPS:
        for path, leaf in leaves(prim.get(group, {})):
            out[prefix + "-".join(path)] = leaf["$value"]
    for sub, prefix in (("duration", "--p-duration-"), ("easing", "--p-easing-")):
        for path, leaf in leaves(prim.get("motion", {}).get(sub, {})):
            out[prefix + "-".join(path)] = leaf["$value"]
    for path, leaf in leaves(prim.get("zIndex", {})):
        out["--p-z-" + "-".join(path)] = leaf["$value"]
    return out


def build_css(root: dict) -> str:
    light, dark = _semantic_names(root)
    prim = _primitive_names(root)
    meta = root.get("meta", {})

    L: list[str] = []
    L.append(f"/* {BANNER} */")
    L.append(f"/* 真源版本：{meta.get('version', '?')}（{meta.get('date', '?')}） */")
    L.append("")
    L.append("/* 主题切换靠根元素的 data-theme 属性（light / dark），默认 light。")
    L.append("   不跟随 prefers-color-scheme —— 本地工程工具应尊重用户的显式选择并记忆。 */")
    L.append("")
    L.append(':root,')
    L.append('[data-theme="light"] {')
    L.append("  color-scheme: light;")
    L.append("")
    L.append("  /* 尺寸 / 字体 / 动效 / 层级 —— 两个主题下取值相同，故只定义一次 */")
    for name, value in prim.items():
        L.append(f"  {name}: {value};")
    L.append("")
    L.append("  /* 语义层（浅色）—— 组件只允许引用这一层的颜色 */")
    for name, value in light.items():
        L.append(f"  {name}: {resolve(value, root)};")
    L.append("}")
    L.append("")
    L.append('[data-theme="dark"] {')
    L.append("  color-scheme: dark;")
    L.append("")
    L.append("  /* 只覆盖语义层颜色 —— 尺寸类无需重定义 */")
    for name in dark:
        L.append(f"  {name}: {resolve(dark[name], root)};")
    L.append("}")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------- JS


def _js_value(value, indent: int) -> str:
    pad = " " * indent
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool) or value is None:
        return json.dumps(value)
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, list):
        inner = ", ".join(_js_value(v, 0) for v in value)
        return f"[{inner}]"
    if isinstance(value, dict):
        items = [
            f"{pad}  {json.dumps(k, ensure_ascii=False)}: {_js_value(v, indent + 2)}"
            for k, v in value.items()
        ]
        return "{\n" + ",\n".join(items) + f",\n{pad}}}"
    die(f"无法序列化的值类型：{type(value).__name__}")


def _strip_internal(node):
    """去掉 `$` 开头的元字段，只留数据。"""
    if isinstance(node, dict):
        return {k: _strip_internal(v) for k, v in node.items() if not k.startswith("$")}
    return node


def _tailwind_theme(root: dict) -> dict:
    """Tailwind 主题扩展。

    ★ **颜色一律引用 CSS 变量**（`var(--c-*)`）而非字面值 ——
      否则深色主题失效（这正是 §3.1 强制颜色走语义层的原因）。
      尺寸类同样引用变量，保证「改 tokens.json 即全局生效」。
    """
    light, _ = _semantic_names(root)
    prim = _primitive_names(root)

    def var(name: str) -> str:
        return f"var({name})"

    colors: dict = {}
    for name in light:
        parts = name[len("--c-"):].split("-")
        node = colors
        for seg in parts[:-1]:
            node = node.setdefault(seg, {})
        node[parts[-1]] = var(name)

    def by_prefix(prefix: str) -> dict:
        return {
            n[len(prefix):]: var(n)
            for n in prim
            if n.startswith(prefix)
        }

    return {
        "colors": colors,
        "spacing": by_prefix("--p-space-"),
        "borderRadius": by_prefix("--p-radius-"),
        "borderWidth": by_prefix("--p-border-"),
        "fontFamily": {k: [var(v)] for k, v in by_prefix("--p-font-").items()},
        "fontSize": by_prefix("--p-font-size-"),
        "boxShadow": by_prefix("--p-shadow-"),
        "zIndex": by_prefix("--p-z-"),
        "transitionDuration": by_prefix("--p-duration-"),
        "transitionTimingFunction": by_prefix("--p-easing-"),
    }


def build_js(root: dict) -> str:
    meta = root.get("meta", {})
    L: list[str] = []
    L.append(f"// {BANNER}")
    L.append(f"// 真源版本：{meta.get('version', '?')}（{meta.get('date', '?')}）")
    L.append("")
    L.append("/** 状态签名 —— 5 态 × (icon + label)。**不得**在组件里手写图标字符。 */")
    L.append("export const stateSignature = " + _js_value(
        _strip_internal(root.get("stateSignature", {})), 0) + ";")
    L.append("")
    L.append("/** 未知态成因（structural / incident）—— 决定是否升至主徽章。 */")
    L.append("export const unknownReason = " + _js_value(
        _strip_internal(root.get("unknownReason", {})), 0) + ";")
    L.append("")
    for section in DATA_SECTIONS[2:]:
        if section not in root:
            continue
        L.append(f"/** {section} —— 真源 design/tokens.json */")
        L.append(f"export const {section} = " + _js_value(
            _strip_internal(root[section]), 0) + ";")
        L.append("")
    L.append("/**")
    L.append(" * Tailwind 主题扩展。颜色与尺寸**一律引用 CSS 变量**（tokens.css），")
    L.append(" * 因此改 design/tokens.json 即全局生效，组件零改动。")
    L.append(" */")
    L.append("export const tailwindTheme = " + _js_value(_tailwind_theme(root), 0) + ";")
    L.append("")
    L.append("export default tailwindTheme;")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------- 预览页


def _swatches(names, root, light: dict, dark: dict) -> str:
    """色板行：色块（**引用 CSS 变量**，随主题实时变化）+ 变量名 + 浅／深两值。

    ⚠️ 首版此处把**浅色字面值**烘焙进 `style="background:..."` ——
      结果切到深色主题后色块仍是浅色（与页面背景矛盾，等于预览页在说谎）。
      改用 `var(--c-*)` 后色块由主题决定；数值列同时给出浅／深两个值，
      这样"两主题是否不同"也一眼可见。
    """
    out = []
    for name in names:
        lo = resolve(light[name], root)
        hi = resolve(dark[name], root)
        shown = lo if lo == hi else f"{lo} ／ {hi}"
        out.append(
            f'      <div class="sw">'
            f'<span class="chip" style="background:var({name})"></span>'
            f'<code>{name}</code><span class="val">{shown}</span></div>'
        )
    return "\n".join(out)


def build_preview(root: dict) -> str:
    light, dark = _semantic_names(root)
    prim = _primitive_names(root)
    sig = _strip_internal(root.get("stateSignature", {}))

    groups: dict[str, list[str]] = {}
    for name in light:
        groups.setdefault(name[len("--c-"):].split("-")[0], []).append(name)

    # 状态签名卡片
    cards = []
    for state, data in sig.items():
        bg, border, fg = (f"--c-contract-{state}-{p}" for p in ("bg", "border", "fg"))
        if bg not in light:
            continue
        cards.append(f"""    <div class="sig" style="background:var({bg});border-color:var({border});color:var({fg})">
      <span class="ic">{data['icon']}</span>
      <span class="lb">{data['label']}</span>
      <code>{state}</code>
    </div>""")

    # 色组
    color_sections = []
    for grp, names in groups.items():
        color_sections.append(
            f'  <h3>{grp}</h3>\n  <div class="grid">\n'
            + _swatches(names, root, light, dark)
            + "\n  </div>"
        )

    # 尺寸 / 圆角 / 描边
    def prim_rows(prefix: str) -> str:
        rows = [(n, v) for n, v in prim.items() if n.startswith(prefix)]
        return "\n".join(
            f'      <div class="sw"><code>{n}</code><span class="val">{v}</span></div>'
            for n, v in rows
        )

    spacing = prim_rows("--p-space-")
    radius = prim_rows("--p-radius-")
    bw = prim_rows("--p-border-")
    shadow = "\n".join(
        f'      <div class="sw"><span class="chip" style="box-shadow:{v};background:var(--c-surface-raised)"></span>'
        f'<code>{n}</code><span class="val">{v}</span></div>'
        for n, v in prim.items() if n.startswith("--p-shadow-")
    )
    motion = prim_rows("--p-duration-") + "\n" + prim_rows("--p-easing-")
    zidx = prim_rows("--p-z-")

    # 字体阶梯
    fs = [(n, v) for n, v in prim.items() if n.startswith("--p-font-size-")]
    typo = "\n".join(
        f'      <div class="typo" style="font-size:{v}"><code>{n}</code>'
        f'<span>142% (MVA 判据) · 12 (0-based) · Pandapower</span></div>'
        for n, v in fs
    )

    meta = root.get("meta", {})
    return f"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="light">
<head>
<meta charset="utf-8">
<title>PowerMCP 设计令牌预览</title>
<link rel="stylesheet" href="src/styles/tokens.css">
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:var(--p-space-8); background:var(--c-surface-base);
         color:var(--c-text-primary); font-family:var(--p-font-sans);
         font-size:var(--p-font-size-body); line-height:1.6; }}
  h1 {{ font-size:var(--p-font-size-display); margin:0 0 var(--p-space-2); }}
  h2 {{ font-size:var(--p-font-size-h1); margin:var(--p-space-10) 0 var(--p-space-3);
        padding-bottom:var(--p-space-2); border-bottom:1px solid var(--c-border-subtle); }}
  h3 {{ font-size:var(--p-font-size-h2); margin:var(--p-space-6) 0 var(--p-space-2);
        color:var(--c-text-secondary); font-weight:500; }}
  code {{ font-family:var(--p-font-mono); font-size:var(--p-font-size-mono);
          color:var(--c-code-fg); background:var(--c-code-bg);
          padding:1px var(--p-space-1); border-radius:var(--p-radius-sm); }}
  .bar {{ display:flex; align-items:center; gap:var(--p-space-4); flex-wrap:wrap; }}
  .muted {{ color:var(--c-text-muted); font-size:var(--p-font-size-bodySm); }}
  button {{ font:inherit; height:32px; padding:0 var(--p-space-4); cursor:pointer;
            background:var(--c-interactive-primary-bg); color:var(--c-interactive-primary-fg);
            border:1px solid transparent; border-radius:var(--p-radius-md); }}
  .grid {{ display:grid; gap:var(--p-space-2);
           grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); }}
  .sw {{ display:flex; align-items:center; gap:var(--p-space-2); padding:var(--p-space-1) 0; }}
  .chip {{ width:20px; height:20px; border-radius:var(--p-radius-sm);
           border:1px solid var(--c-border-subtle); flex:none; }}
  .val {{ margin-left:auto; color:var(--c-text-muted); font-size:var(--p-font-size-caption);
          font-family:var(--p-font-mono); }}
  .sigs {{ display:grid; gap:var(--p-space-3);
           grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); }}
  .sig {{ border:1px solid; border-radius:var(--p-radius-lg);
          padding:var(--p-space-4); display:flex; align-items:center; gap:var(--p-space-2); }}
  .sig .ic {{ font-size:var(--p-font-size-h1); }}
  .sig .lb {{ font-weight:500; }}
  .sig code {{ margin-left:auto; background:transparent; color:inherit; }}
  .typo {{ padding:var(--p-space-2) 0; border-bottom:1px dashed var(--c-border-subtle);
           display:flex; align-items:baseline; gap:var(--p-space-4); }}
  .typo span {{ color:var(--c-text-secondary); }}
</style>
</head>
<body>
<div class="bar">
  <h1 style="margin:0">PowerMCP 设计令牌预览</h1>
  <button id="toggle">切换深色</button>
</div>
<p class="muted">
  由 <code>tools/build_design_tokens.py</code> 从 <code>design/tokens.json</code> 生成 —— 勿手改。<br>
  真源版本 {meta.get('version', '?')}（{meta.get('date', '?')}）。
  本页直接引用生成产物 <code>src/styles/tokens.css</code>，因此它绿 = 生成链是通的。
</p>

<h2>状态签名（5 态 × 色 + 图标 + 标签）</h2>
<p class="muted">颜色<strong>不得</strong>单独承载信息 —— 每个状态必须同时含图标与文字（P2）。</p>
<div class="sigs">
{chr(10).join(cards)}
</div>

<h2>语义色（组件只允许引用这一层）</h2>
<p class="muted">原始层颜色<strong>不</strong>暴露为 CSS 变量 —— 否则深色主题失效（§3.1）。
色块<strong>随主题实时变化</strong>；数值列左为浅色、右为深色（两者相同时只显示一个）。</p>
{chr(10).join(color_sections)}

<h2>间距</h2>
<div class="grid">
{spacing}
</div>

<h2>圆角</h2>
<div class="grid">
{radius}
</div>

<h2>描边宽度</h2>
<div class="grid">
{bw}
</div>

<h2>阴影</h2>
<div class="grid">
{shadow}
</div>

<h2>动效</h2>
<div class="grid">
{motion}
</div>

<h2>层级</h2>
<div class="grid">
{zidx}
</div>

<h2>字号阶梯</h2>
<div>
{typo}
</div>

<script>
  // 支持 file:// 下直接验证深色主题：preview.html#dark
  if (location.hash === '#dark') {{
    document.documentElement.setAttribute('data-theme', 'dark');
  }}
  var btn = document.getElementById('toggle');
  var sync = function () {{
    var dark = document.documentElement.getAttribute('data-theme') === 'dark';
    btn.textContent = dark ? '切换浅色' : '切换深色';
  }};
  btn.addEventListener('click', function () {{
    var dark = document.documentElement.getAttribute('data-theme') === 'dark';
    document.documentElement.setAttribute('data-theme', dark ? 'light' : 'dark');
    sync();
  }});
  sync();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------- 入口


def main(argv: list[str]) -> int:
    check = "--check" in argv
    root = load()
    artifacts = (
        (OUT_CSS, build_css(root)),
        (OUT_JS, build_js(root)),
        (OUT_PREVIEW, build_preview(root)),
    )

    if check:
        drift = []
        for path, expected in artifacts:
            if not path.exists():
                drift.append(f"缺少产物：{path.relative_to(ROOT)}")
            elif path.read_text(encoding="utf-8") != expected:
                drift.append(f"产物与真源不一致：{path.relative_to(ROOT)}")
        if drift:
            print("[FAIL] 设计令牌产物已漂移 —— 请运行 `python tools/build_design_tokens.py`")
            for d in drift:
                print(f"   - {d}")
            return 1
        print("[OK] 设计令牌产物与 design/tokens.json 一致。")
        return 0

    for path, text in artifacts:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"[OK] 已生成 {path.relative_to(ROOT)}（{len(text.splitlines())} 行）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
