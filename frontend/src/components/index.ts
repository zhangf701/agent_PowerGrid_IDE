/** 组件统一出口 —— 视图只从这里 import，不直接深入具体文件。
 *
 *  分组（UI 规范 v2 §4.0）：
 *  - **A 组 · 常驻**：`Signature` · `Quantity` · `Identifier` · 基础件（§4.6）
 *    —— 约束的是**数值与标识符的写法**，在任何视图都适用，故始终可见。
 *  - **B 组 · 校验层**（默认折叠）：`ContractBadge` / `ContractCard` / `ToolCallRow` —— **尚未实现**，
 *    随 ⑥ 校验层视图（S3）落地。
 *  - **C 组 · 研究视图**（§4.7）：`SkillCard` · `CaseCard` · `ExperimentGrid` · `ResultTable` 已落地；
 *    `ModuleBadge` 随所属视图落地。
 *
 *  ⚠️ **`EngineStatusIndicator`（§4.6.6，规范标为 P1 必做）本步未做** ——
 *    它需要 `EngineStatus` 五值（running/starting/degraded/crashed/circuit-open），
 *    而网关侧「进程监管」（§11.3 心跳 / 熔断）**尚未实现**（源码 0 命中），
 *    现在建就是**对着不存在的数据定型**。待进程监管落地（P3）或 S2 对话分析需要时再做。
 */

export { Signature, signatureOf } from "./Signature";
export type { SignatureKey, KnownState, StateSignature } from "./Signature";

export { Button } from "./Button";
export type { ButtonProps, ButtonVariant, ButtonSize } from "./Button";

export { Input } from "./Input";

export { EmptyState, ErrorBanner, ErrorState, LoadingState } from "./states";

export { Quantity, measure, MeasureError } from "./Quantity";
export type { Criterion, Measured, Unit, UnitSpec } from "./Quantity";

export { Identifier, deriveConvention, conventionSuffix } from "./Identifier";
export type { Convention, EngineId } from "./Identifier";

export { SkillCard, KIND_LABEL, KIND_SIG } from "./SkillCard";

export { CaseCard, fmtBytes, parentOf, registrationBasis } from "./CaseCard";

export {
  ExperimentGrid,
  cellSignature,
  bindingText,
  firstFailure,
  orderMetricKeys,
  INLINE_METRIC_LIMIT,
} from "./ExperimentGrid";
export type { GridCell, GridStep, GridPlannedStep } from "./ExperimentGrid";
export { ExperimentProposalCard } from "./ExperimentProposalCard";

export { ResultTable, cellValue } from "./ResultTable";

/* ── B 组 · 校验层（默认折叠，能力不丢）── */

export { ContractBadge, CONTRACT_NAMES, signatureKeyOf } from "./ContractBadge";
export type { ContractState, UnknownReason } from "./ContractBadge";

export { ContractCard } from "./ContractCard";

export { VerificationLayer, summarizeFindings } from "./VerificationLayer";
export type { ContractSummary } from "./VerificationLayer";

export { ToolCallRow, declaredOutputs, OUTPUT_ARG_KEYS } from "./ToolCallRow";
export type { ToolCallRowProps } from "./ToolCallRow";

export { ResultSummary } from "./ResultSummary";
export type { ResultItem, ResultId } from "./ResultSummary";

export { ViolationTable, DEFAULT_MAX_ROWS } from "./ViolationTable";
/* ViolationItem / VoltageSeries 由 `../results` 直接导出 ——
   ⚠️ 不经本出口中转运行时值：results.ts 已依赖本出口（measure/deriveConvention），
   再把 results 的运行时值回灌进来会补全一条循环链。类型仅此处中转是安全的。 */
export type { ViolationItem, VoltageSeries } from "../results";

export { CrossEnginePanel } from "./CrossEnginePanel";
export { CapabilityMatrixPanel } from "./CapabilityMatrixPanel";
export { IrInspectorPanel } from "./IrInspectorPanel";
