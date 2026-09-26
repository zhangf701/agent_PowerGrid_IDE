/** Identifier —— UI 规范 v2 §4.5。
 *
 *  ★ 为什么需要（实测缺陷）：pandapower 用 **0-based 索引**，PyPSA 沿用 IR 的 **1-based 标识**。
 *    按字面键直接比对，会把跨引擎偏差**从 8.84e-11 pu 放大到 0.027806 pu —— 放大 3.1 亿倍**，
 *    且会拿不同物理元件做对比。故「标识符必须标注约定」被做成组件。
 *
 *  ★ 三重防护：
 *    ① `engine` 是 9 个 server id 的**字面量联合** → 写 `engine="PyPSA"` 是**编译错误**；
 *    ② 查表未命中 → `unknown`（**绝不猜一个值**）；
 *    ③ 显式传 `convention` 且与 `engine` 矛盾 → **抛错**（人工断言与引擎事实冲突）。
 *
 *  ⚠️ **残余代价（规范已声明）**：`convention` 在类型上仍可由调用点显式传入，
 *    无法禁止 —— 可能有人为了让表格好看而写死一个值。**这条最终仍要靠 code review**，
 *    本组件不宣称被类型系统完全覆盖。
 *
 *  ★ 约定表来自**生成物** `tokens.generated.js`（真源 `design/tokens.json`），
 *    **不在组件里手抄** —— 手抄的表与真源漂移时会静默标错约定，正是本组件要防的缺陷。
 */
import { identifierConvention } from "../design/tokens.generated.js";

/** 9 个 server id 的字面量联合 —— 与 `powermcp/registry.py` 的 `Tool.name` 一致，**不得写显示名**。 */
export type EngineId =
  | "pandapower"
  | "pypsa"
  | "surge"
  | "andes"
  | "egret"
  | "opendss"
  | "hope"
  | "genx"
  | "powerio";

/** 三态，含 unknown —— 与四态契约状态同理：**未知必须可表达**。 */
export type Convention = "0-based" | "1-based" | "unknown";

const CONVENTIONS: readonly Convention[] = ["0-based", "1-based", "unknown"];

function asConvention(v: unknown): Convention {
  return CONVENTIONS.includes(v as Convention) ? (v as Convention) : "unknown";
}

/** 由 engine 查表推导约定。**engine 缺省或查表未命中 → `unknown`**（兜底不是 `0-based`）。 */
export function deriveConvention(engine?: EngineId): Convention {
  if (!engine) return "unknown";
  const table = identifierConvention.byEngine as Record<string, unknown>;
  return asConvention(table[engine]);
}

/** 约定后缀文案（如 `(0-based)` / `(约定未知)`），取自生成物。 */
export function conventionSuffix(conv: Convention): string {
  const suffix = identifierConvention.suffix as Record<string, string>;
  return suffix[conv] ?? suffix.unknown ?? "(约定未知)";
}

/** 等宽 —— ★ 用令牌类 `font-mono`（`tools/build_design_tokens.py` 的 F-2 已修，
 *  此前只能写内联 `style` 绕过坏掉的 `fontFamily` 令牌）。 */
const MONO = "font-mono";

export function Identifier({
  id,
  convention,
  engine,
  /** 元件类型。**不作封闭枚举** —— 引擎实际类型含 line/trafo/trafo3w/ext_grid/... ，
   *  封闭枚举会逼出 `as any` 强转。 */
  kind,
}: {
  id: number | string;
  convention?: Convention;
  engine?: EngineId;
  kind?: string;
}) {
  const derived = deriveConvention(engine);

  // ③ 人工断言与引擎事实冲突 → 抛错，不静默采信任何一方
  if (convention && engine && convention !== derived) {
    throw new Error(
      `Identifier: 显式约定 \`${convention}\` 与引擎 \`${engine}\` 的约定 \`${derived}\` 冲突 —— ` +
        "两者必有一个错，不能都信（§4.5 三重防护 ③）。",
    );
  }

  const conv = convention ?? derived;
  return (
    <span
      className="whitespace-nowrap"
      title={`${kind ? `${kind} · ` : ""}约定来源：${engine ?? "未指定引擎"}`}
    >
      <span className={MONO}>{id}</span>{" "}
      <span className="text-text-muted">{conventionSuffix(conv)}</span>
    </span>
  );
}
