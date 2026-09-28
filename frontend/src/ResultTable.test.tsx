/** ResultTable 测试 —— 钉住「网格说『见结果表』，那张表必须真的在，且列一个不少」。
 *
 *  ★ 这条来自真实缺陷：`ExperimentGrid` 行内只显示 `INLINE_METRIC_LIMIT`（4）项指标，
 *    排在字母序后面的 `metric.results.n_buses` 在界面上**无处可见**
 *    （实测行内只剩 areas.count / base_mva / freq_hz / n_areas）。
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { ResultTable, cellValue } from "./components";
import type { ResultColumn, ResultRow } from "./api";

afterEach(cleanup);

const COLUMNS: ResultColumn[] = [
  { key: "index", title: "格", type: "number" },
  { key: "case_id", title: "算例", type: "text" },
  { key: "status", title: "状态", type: "state" },
  { key: "ran_at", title: "执行时间", type: "text" },
  { key: "metric.results.areas.count", title: "metric.results.areas.count", type: "number" },
  { key: "metric.results.base_mva", title: "metric.results.base_mva", type: "number" },
  { key: "metric.results.n_buses", title: "metric.results.n_buses", type: "number" },
];

function row(over: Partial<ResultRow> = {}): ResultRow {
  return {
    index: 0,
    case_id: "cd4cf1328477",
    bindings: {},
    cache_key: "k0",
    status: "completed",
    ran_at: null,
    metrics: {
      "metric.results.areas.count": 1,
      "metric.results.base_mva": 100,
      "metric.results.n_buses": 39,
    },
    ...over,
  };
}

describe("cellValue —— 先看行顶层，再落到 metrics", () => {
  it("保留列取行顶层字段", () => {
    expect(cellValue(row(), "case_id")).toBe("cd4cf1328477");
    expect(cellValue(row(), "index")).toBe(0);
  });

  it("指标列取 row.metrics（键是 `metric.*`，不在行顶层）", () => {
    expect(cellValue(row(), "metric.results.n_buses")).toBe(39);
  });

  it("缺失值返回 undefined（由渲染层显示为 —，不猜 0）", () => {
    expect(cellValue(row(), "metric.not.there")).toBeUndefined();
  });
});

describe("ResultTable —— 全部列都渲染，一个不少", () => {
  it("★ 排在字母序后面的指标列（n_buses）也在表里", () => {
    render(<ResultTable columns={COLUMNS} rows={[row()]} />);
    const table = screen.getByTestId("result-table");
    expect(table.textContent).toContain("metric.results.n_buses");
    expect(table.textContent).toContain("39");
  });

  it("列数 = columns 长度（不是被截断的 4 列）", () => {
    const { container } = render(<ResultTable columns={COLUMNS} rows={[row()]} />);
    expect(container.querySelectorAll("thead th")).toHaveLength(COLUMNS.length);
  });

  it("状态列走 Signature：图标 + 中文标签（去掉颜色仍可读）", () => {
    const { container } = render(<ResultTable columns={COLUMNS} rows={[row()]} />);
    // completed → satisfied → ✔ 完成
    expect(container.textContent).toContain("完成");
    expect(container.textContent).toContain("✔");
  });

  it("空列定义 → 不渲染（不留空表壳）", () => {
    render(<ResultTable columns={[]} rows={[]} />);
    expect(screen.queryByTestId("result-table")).toBeNull();
  });

  it("多行都渲染", () => {
    const { container } = render(
      <ResultTable columns={COLUMNS} rows={[row(), row({ index: 1, cache_key: "k1" })]} />,
    );
    expect(container.querySelectorAll("tbody tr")).toHaveLength(2);
  });
});
