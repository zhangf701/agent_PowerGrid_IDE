#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校验 design/tokens.json（令牌单一真源）与 docs/PowerMCP_UI设计规范.md 的一致性。

背景：本项目根目录非 git 仓库，文档与代码两处手抄同一份色值无法靠版本控制兜底
（2026-09-24 已发生过一次交付物被覆盖且不可恢复的事故）。本脚本是该风险的技术缓解。

校验四项：
  1. JSON 合法 + 所有别名引用可解析
  2. 单一真源一致性 —— 规范文档中出现的每个 `--c-*` / `--p-*` 令牌，其值与 JSON 逐字符相同
  3. 完整性 —— 4 个契约状态 × 2 主题 × 3 个颜色分量齐备
  4. **派生产物一致性** —— `frontend/src/styles/tokens.css` 的令牌名集合与文档完全一致
     （防 `tools/build_design_tokens.py` 里那份**复制来的**命名映射表与本文档漂移）

用法：
    python tools/check_design_tokens.py            # 校验
    python tools/check_design_tokens.py -v         # 附带逐项明细

退出码：0 = 通过；1 = 校验失败。
"""

import json
import re
import sys
from pathlib import Path

# Windows 控制台默认 GBK，中文输出会抛 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

ROOT = Path(__file__).resolve().parent.parent
TOKENS_JSON = ROOT / "design" / "tokens.json"
SPEC_MD = ROOT / "docs" / "PowerMCP_UI设计规范.md"
GEN_CSS = ROOT / "frontend" / "src" / "styles" / "tokens.css"

# 规范文档中的路径别名（JSON 路径段 -> CSS 变量名段）
SEGMENT_RENAME = {"categorical": "cat"}

# 这些令牌存在于 JSON 但不在规范文档的令牌表中 —— 属预期，不是错误。
#   - primitive.color.*  ：原始层，仅供语义层引用，不对开发者暴露
#   - lineHeight/fontWeight：由字号阶梯表以「行高 / 字重」列表达，不单独出 CSS 变量
NOT_DOCUMENTED = ("primitive.color", "primitive.lineHeight", "primitive.fontWeight")

REQUIRED_STATES = ("satisfied", "degraded", "violated", "unknown", "incident")
STATE_PARTS = ("bg", "border", "fg")


def die(msg):
    print(f"\n[FAIL] {msg}")
    sys.exit(1)


def load_tokens():
    if not TOKENS_JSON.exists():
        die(f"令牌真源不存在：{TOKENS_JSON}")
    try:
        return json.loads(TOKENS_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"tokens.json 不是合法 JSON：line {e.lineno} col {e.colno} — {e.msg}")


def resolve(value, root, seen=()):
    """解析 {a.b.c} 形式的别名引用。"""
    if not isinstance(value, str):
        return value
    m = re.fullmatch(r"\{([^}]+)\}", value.strip())
    if not m:
        return value

    path = m.group(1)
    if path in seen:
        die(f"别名循环引用：{' -> '.join(seen + (path,))}")

    node = root
    for seg in path.split("."):
        if not isinstance(node, dict) or seg not in node:
            die(f"别名无法解析：{{{path}}}（在 {seg} 处断裂）")
        node = node[seg]

    if isinstance(node, dict) and "$value" in node:
        return resolve(node["$value"], root, seen + (path,))
    die(f"别名指向的不是叶子令牌：{{{path}}}")


def walk_leaves(node, prefix=()):
    """深度遍历，产出 (路径段元组, 叶子字典)。"""
    if isinstance(node, dict):
        if "$value" in node:
            yield prefix, node
            return
        for k, v in node.items():
            if k.startswith("$"):
                continue
            yield from walk_leaves(v, prefix + (k,))


def sval(x):
    """统一成字符串 —— JSON 中数值型令牌（zIndex / fontWeight）与文档中的文本比较。"""
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return str(x)


def build_expected(root):
    """从 tokens.json 构建 {css_var: (值, ...)} 期望表。"""
    expected = {}

    # --- 语义层：--c-<path>  ->  (浅色值, 深色值) ---
    themes = root.get("semantic", {})
    for theme in ("light", "dark"):
        if theme not in themes:
            die(f"semantic 缺少主题：{theme}")
        for path, leaf in walk_leaves(themes[theme]):
            name = "--c-" + "-".join(SEGMENT_RENAME.get(s, s) for s in path)
            val = sval(resolve(leaf["$value"], root))
            expected.setdefault(name, {})[theme] = val

    for name, pair in expected.items():
        if "light" not in pair or "dark" not in pair:
            die(f"{name} 未在浅/深两主题中成对定义")
        expected[name] = (pair["light"], pair["dark"])

    # --- 原始层：按组映射到 CSS 变量名 ---
    prim = root.get("primitive", {})
    group_map = [
        ("space", "--p-space-"),
        ("radius", "--p-radius-"),
        ("fontSize", "--p-font-size-"),
        ("borderWidth", "--p-border-"),
        ("fontFamily", "--p-font-"),
        ("shadow", "--p-shadow-"),
    ]
    for group, prefix in group_map:
        for path, leaf in walk_leaves(prim.get(group, {})):
            expected[prefix + "-".join(path)] = (sval(resolve(leaf["$value"], root)),)

    for path, leaf in walk_leaves(prim.get("motion", {}).get("duration", {})):
        expected["--p-duration-" + "-".join(path)] = (sval(resolve(leaf["$value"], root)),)
    for path, leaf in walk_leaves(prim.get("motion", {}).get("easing", {})):
        expected["--p-easing-" + "-".join(path)] = (sval(resolve(leaf["$value"], root)),)
    for path, leaf in walk_leaves(prim.get("zIndex", {})):
        expected["--p-z-" + "-".join(path)] = (sval(resolve(leaf["$value"], root)),)

    return expected


TOKEN_CELL = re.compile(r"^`(--[A-Za-z0-9][A-Za-z0-9-]*)`$")
VALUE_CELL = re.compile(r"^`([^`]+)`$")


# 只在这些章节内解析令牌表。
# 其余章节（如 §6.2 ECharts 主题、§8.2 shadcn 映射）的表格会出现「以令牌名作值」
# 或「外部库变量名」的写法，不属于令牌表的范围，误解析会产生假阳性。
PARSE_REGIONS = (
    ("# 三、设计令牌", "# 四、组件规范"),
    ("# 九、附录", "## 附录 B"),
)


def scoped_lines(text):
    lines = text.splitlines()
    keep = [False] * len(lines)
    for start_marker, end_marker in PARSE_REGIONS:
        try:
            start = next(i for i, l in enumerate(lines) if l.startswith(start_marker))
        except StopIteration:
            die(f"规范文档缺少章节标记：{start_marker}")
        end = len(lines)
        for i in range(start + 1, len(lines)):
            if lines[i].startswith(end_marker):
                end = i
                break
        for i in range(start, end):
            keep[i] = True
    return [(i + 1, l) for i, (k, l) in enumerate(zip(keep, lines)) if k]


def parse_spec(text, expected):
    """
    从规范文档的令牌表章节中抽取 (令牌 -> 值元组)。

    规则：一行的某个单元格是 `--xxx` 时，紧随其后的、同样用反引号包裹的连续单元格即其值。
    遇到非反引号单元格（如「用途」列的文字）即停止吸收。

    抽取到的值会按令牌的固有元数截断：令牌表右侧可能还有描述性列（如 §3.2.3 的
    「绑定 server id」，同样带反引号），它们不是令牌的值，必须排除，
    否则同一令牌在 §3.2.3 与附录 A 会被判为「取值不同」。
    """
    found = {}
    for lineno, line in scoped_lines(text):
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]

        for i, cell in enumerate(cells):
            m = TOKEN_CELL.match(cell)
            if not m:
                continue
            token = m.group(1)
            values = []
            for nxt in cells[i + 1:]:
                vm = VALUE_CELL.match(nxt)
                if not vm:
                    break
                values.append(vm.group(1))
            if not values:
                continue
            if token in expected:
                values = values[:len(expected[token])]
            if token in found and found[token] != tuple(values):
                die("规范文档内 {} 出现两次且取值不同：{} vs {}".format(
                    token, found[token], tuple(values)))
            found[token] = tuple(values)
    return found


def check_completeness(root):
    """4 个契约状态 × 2 主题 × 3 个颜色分量。"""
    problems = []
    for theme in ("light", "dark"):
        contract = root.get("semantic", {}).get(theme, {}).get("contract", {})
        for state in REQUIRED_STATES:
            if state not in contract:
                problems.append(f"semantic.{theme}.contract 缺状态：{state}")
                continue
            for part in STATE_PARTS:
                if part not in contract[state]:
                    problems.append(f"semantic.{theme}.contract.{state} 缺分量：{part}")
    sig = root.get("stateSignature", {})
    for state in REQUIRED_STATES:
        node = sig.get(state, {})
        for field in ("icon", "label"):
            if not node.get(field):
                problems.append(f"stateSignature.{state} 缺字段：{field}")
    return problems


def check_generated_css(doc_tokens: set):
    """派生产物一致性：生成的 CSS 令牌名集合与文档**完全一致**。

    ★ 为什么需要：`tools/build_design_tokens.py` 复制了一份「JSON 路径 → CSS 变量名」
      映射表（与本文档的 `build_expected` 同源）。**两处一旦漂移，生成的 CSS 会与
      文档校验的令牌名对不上** —— 那是最该防的失败模式（前端拿到的是错的变量名，
      而文档校验却是绿的）。

    Returns:
        `(仅在CSS中, 仅在文档中)`；**产物不存在时返回 None**（前端工程尚未生成产物属正常）。
    """
    if not GEN_CSS.exists():
        return None
    css = GEN_CSS.read_text(encoding="utf-8")
    gen = set(re.findall(r"^\s*(--[A-Za-z0-9-]+):", css, re.M))
    return sorted(gen - doc_tokens), sorted(doc_tokens - gen)


def main():
    verbose = "-v" in sys.argv

    print("=" * 66)
    print("PowerMCP UI 设计令牌一致性校验")
    print("=" * 66)

    root = load_tokens()
    print(f"[1/4] JSON 合法，别名全部可解析                OK")

    expected = build_expected(root)
    print(f"      期望令牌数：{len(expected)}（含 JSON 中未暴露给文档的原始层）")

    if not SPEC_MD.exists():
        die(f"规范文档不存在：{SPEC_MD}")
    text = SPEC_MD.read_text(encoding="utf-8")
    found = parse_spec(text, expected)
    print(f"[2/4] 规范文档中抽到令牌：{len(found)}")

    mismatched, unknown, missing_doc = [], [], []
    for token, vals in found.items():
        if token not in expected:
            unknown.append(token)
            continue
        exp = expected[token]
        # 只比对到令牌的固有元数（语义色=2：浅/深；其余=1）。
        # 令牌表右侧可能还有描述性列（如 §3.2.3 的「绑定 server id」），
        # 它们也带反引号，但不是令牌的值，不应参与比对。
        if exp != vals[:len(exp)]:
            mismatched.append((token, exp, vals))

    for token, exp in expected.items():
        if token in found:
            continue
        if any(token.startswith(p) for p in NOT_DOCUMENTED):
            continue
        missing_doc.append(token)

    if verbose:
        print("\n  --- 逐项明细 ---")
        for token in sorted(found):
            mark = "!!" if token in unknown or any(t == token for t, _, _ in mismatched) else "OK"
            print(f"  [{mark}] {token} = {' | '.join(found[token])}")

    problems = check_completeness(root)
    print(f"[3/4] 状态签名完整性检查：{'OK' if not problems else 'FAIL'}")

    drift = check_generated_css(set(found))
    if drift is None:
        print(f"[4/4] 派生产物一致性：跳过（{GEN_CSS.relative_to(ROOT)} 尚未生成）")
        css_extra, css_missing = [], []
    else:
        css_extra, css_missing = drift
        print(f"[4/4] 派生产物一致性：{'OK' if not (css_extra or css_missing) else 'FAIL'}")

    print()
    ok = True
    if mismatched:
        ok = False
        print(f"❌ 值不一致（{len(mismatched)} 项）—— 文档与 tokens.json 已漂移：")
        for token, exp, got in mismatched:
            print(f"   {token}")
            print(f"      JSON    : {' | '.join(exp)}")
            print(f"      规范文档: {' | '.join(got)}")
    if unknown:
        ok = False
        print(f"❌ 文档中出现但 JSON 中不存在（{len(unknown)} 项）：")
        for token in sorted(unknown):
            print(f"   {token}")
    if missing_doc:
        ok = False
        print(f"❌ JSON 中存在但规范文档未列出（{len(missing_doc)} 项）：")
        for token in sorted(missing_doc):
            print(f"   {token}")
    if problems:
        ok = False
        print(f"❌ 状态签名不完整（{len(problems)} 项）：")
        for p in problems:
            print(f"   {p}")

    if css_extra or css_missing:
        ok = False
        print("❌ 生成的 CSS 与文档令牌名不一致 —— 命名映射表已漂移：")
        if css_extra:
            print(f"   仅在 tokens.css 中（{len(css_extra)} 项）：{css_extra}")
        if css_missing:
            print(f"   仅在文档中（{len(css_missing)} 项）：{css_missing}")
        print("   修法：对齐 tools/build_design_tokens.py 与本文档的命名映射，再重新生成。")

    print("-" * 66)
    if ok:
        print("✅ 校验通过：规范文档与令牌真源一致。")
        tail = "" if drift is None else "；派生产物 tokens.css 与文档一致"
        print(f"   {len(found)} 个令牌逐值比对无误；"
              f"{len(REQUIRED_STATES)} 个契约状态 × 2 主题 × {len(STATE_PARTS)} 分量齐备"
              f"（{'/'.join(REQUIRED_STATES)}）{tail}。")
        return 0
    print("❌ 校验失败。修改请改 design/tokens.json，文档表格从它抄录。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
