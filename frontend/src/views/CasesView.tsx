/** ② 算例库视图 —— 方案 v4 §4.2「研究什么」。
 *
 *  ★ 算例是 v4 引入的**新一级实体**（v3 只有 session 粒度，研究无法「组织」）。
 *  ★ 三条必须可见的东西（都来自 §4.7.2 硬规则，见 `CaseCard`）：
 *    现算的可用性 / 漂移（含基准）/ 围笼可读性（含**可执行指引**）。
 *  ★ **围笼 409 分支**是本视图要真正跑通的一条：项目外算例能登记（只记路径不读文件），
 *    但**解析会被 409 拦下**，并给出「把哪个目录加进 `POWERIO_MCP_ALLOWED_ROOTS`」。
 *
 *  ⚠️ **与 MVP 的一处有意差异**：MVP 把操作反馈（已登记 / 已解析 / 已注销）写到**对话流**里，
 *    而 ③ 对话分析尚未迁移 —— 故本视图把反馈就地显示在面板内。待 S2 落地后应改为
 *    §4.6.4 的 `Toast`（`info` 类型：操作已发生）。
 */
import { useCallback, useEffect, useState, type ReactNode } from "react";

import {
  CaseParseResponseSchema,
  CaseRegisterResponseSchema,
  CaseUnregisterResponseSchema,
  CasesResponseSchema,
  SchemaDriftError,
  apiParsed,
  type CasesResponse,
} from "../api";
import { Button, CaseCard, EmptyState, ErrorBanner, Input, LoadingState, fmtBytes } from "../components";

type Sig = "violated" | "incident";

export function CasesView() {
  const [data, setData] = useState<CasesResponse | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [path, setPath] = useState("");
  const [note, setNote] = useState<ReactNode>(null);
  const [error, setError] = useState<{ message: string; sig: Sig } | null>(null);

  /** ★ 每次操作后**重新拉取** —— `available` / `drift` 是服务端现算的，前端不缓存（§4.7.2 硬规则 1）。 */
  const reload = useCallback(async () => {
    try {
      setData(await apiParsed("/cases", CasesResponseSchema));
      setError(null);
    } catch (err) {
      setError({
        message: (err as Error).message,
        sig: err instanceof SchemaDriftError ? "incident" : "violated",
      });
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function act<T>(fn: () => Promise<T>, onOk: (r: T) => ReactNode) {
    setError(null);
    // ★ 新操作的反馈必须先清掉上一次的 —— 否则「A 成功的提示」会残留在
    //   「B 失败的横幅」旁边，被误读成 B 的结果（2026-09-27 张老师真机测试踩中：
    //   case39 解析成功 → case_fencetest.m 解析 409，残留的 case39 提示被当成后者的结果）。
    setNote(null);
    try {
      setNote(onOk(await fn()));
    } catch (err) {
      setError({
        message: (err as Error).message,
        sig: err instanceof SchemaDriftError ? "incident" : "violated",
      });
    } finally {
      await reload();
    }
  }

  async function register() {
    const p = path.trim();
    if (!p) {
      setError({ message: "请先填算例文件的绝对路径", sig: "violated" });
      return;
    }
    await act(
      () =>
        apiParsed("/cases", CaseRegisterResponseSchema, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: p }),
        }),
      (r) => {
        setPath("");
        // ★ 归一化**不静默**：路径被自动改动时必须让用户看见
        const norm = r.path_normalized?.length
          ? `（路径已自动归一化：${r.path_normalized.join("、")}）`
          : "";
        return `${r.created ? "已登记算例" : "该路径已登记过，已更新"}${norm}`;
      },
    );
  }

  async function parse(id: string) {
    setBusyId(id);
    // ★ 反馈带上算例名 —— 面板内的提示是全局的，不带名字就会被安到别的算例头上
    const label = data?.cases.find((c) => c.id === id)?.label ?? id;
    await act(
      () =>
        apiParsed(`/cases/${id}/parse`, CaseParseResponseSchema, { method: "POST" }),
      (r) =>
        `已解析 ${label}：${r.value_type}（${fmtBytes(r.ir_bytes)}，IR 可读：${r.has_ir ? "是" : "否"}）`,
    );
    setBusyId(null);
  }

  async function unregister(id: string) {
    await act(
      () => apiParsed(`/cases/${id}`, CaseUnregisterResponseSchema, { method: "DELETE" }),
      () => (
        <>
          已注销登记（<strong>源文件未删除</strong>）
        </>
      ),
    );
    setSelected((s) => (s === id ? null : s));
  }

  return (
    <section aria-label="算例库">
      <h2 className="mb-2 mt-4 text-h2 font-medium">算例库</h2>

      {error && <ErrorBanner sig={error.sig} message={error.message} />}
      {note && (
        <div className="mb-2 rounded-md border border-border-subtle bg-surface-sunken px-3 py-2 text-bodySm text-text-secondary">
          {note}
        </div>
      )}

      {!data && !error && <LoadingState label="加载中…（等待 /cases）" />}

      {data &&
        (data.cases.length ? (
          data.cases.map((c) => (
            <CaseCard
              key={c.id}
              c={c}
              selected={selected === c.id}
              busy={busyId === c.id}
              onSelect={() => setSelected((s) => (s === c.id ? null : c.id))}
              onParse={() => void parse(c.id)}
              onUnregister={() => void unregister(c.id)}
            />
          ))
        ) : (
          <EmptyState>还没有算例。在下面填路径登记一个。</EmptyState>
        ))}

      <div className="mt-2 flex gap-2">
        <Input
          value={path}
          onChange={(e) => setPath(e.target.value)}
          placeholder="算例文件的绝对路径"
          className="min-w-0 flex-1"
          aria-label="算例文件的绝对路径"
        />
        <Button onClick={() => void register()}>登记</Button>
      </div>

      <div className="mt-1.5 text-bodySm text-text-muted">
        登记只记路径与哈希，<strong>不复制文件</strong>；注销也<strong>不会删你的文件</strong>。
      </div>
    </section>
  );
}
