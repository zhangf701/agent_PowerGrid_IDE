/** ③ 对话分析视图 —— 方案 v4 §4.3「怎么研究」（**主界面**）。
 *
 *  ★ Agent 循环在**网关侧**（2026-09-25 裁决）：模型只输出 tool_call JSON，
 *    工具执行经 `proxy.call_tool` —— 故契约 3 的 fail-closed 校验、EVIDENCE 发布、
 *    NDJSON 审计**天然在环内**。
 *
 *  ★ **两条流，语义不同**（勿混淆）：
 *    - `POST /sessions/{sid}/chat`：`event:` = 对话 kind（text/final/notice/error/
 *      tool_call/tool_error），**无 `id:`**，`data:` 是 payload 本身；
 *    - `GET /sessions/{sid}/events`：`event:` = **通道**，`id:` = 单调 `seq`，
 *      `data:` = `{seq, kind, payload, at}`。
 *    会话与事件流由 `useSession()` 提到 App 层（校验层状态条「所有视图共有」）；
 *    本视图只管**一轮对话的流**与**回合的组装**。
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { parseChatFrame, type ChatFrame } from "../api";
import { Button, ErrorBanner, Input, LoadingState, ToolCallRow } from "../components";
import type { SessionStream } from "../session";
import { readSse } from "../sse";

export interface Turn {
  id: number;
  question: string;
  /** 流式累积的回答；`final` 到达时被完整文本覆盖 */
  answer: string;
  notices: string[];
  /** 本轮整体失败（`error` 帧） */
  failure?: string;
}

/* ────────────────────── 纯函数：便于直接单测（不经 fetch / 流） ────────────────────── */

/** 应用一个 chat 帧。★ `tool_call`/`tool_error` 帧**有意忽略** ——
 *  轨迹取自 evidence 通道（有 `seq`、可去重、重连可重放），渲染两处会重复计数。 */
export function applyChatFrame(turns: Turn[], id: number, f: ChatFrame): Turn[] {
  const patch = (fn: (t: Turn) => Turn) => turns.map((t) => (t.id === id ? fn(t) : t));
  switch (f.kind) {
    case "text":
      return patch((t) => ({ ...t, answer: t.answer + f.text }));
    case "final":
      // 完整回答**覆盖**累积文本（否则会重复一遍）
      return patch((t) => ({ ...t, answer: f.text }));
    case "notice":
      return patch((t) => ({ ...t, notices: [...t.notices, f.detail] }));
    case "error":
      return patch((t) => ({ ...t, failure: f.detail }));
    default:
      return turns;
  }
}

/* ────────────────────────────────── 视图 ────────────────────────────────── */

export function ChatView({ session }: { session: SessionStream }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState<{ message: string; sig: "violated" | "incident" } | null>(null);

  const nextTurnId = useRef(1);
  const streamRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = streamRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || !session.sid) return;

    const id = nextTurnId.current++;
    session.setActiveTurn(id); // ★ 之后到达的 evidence 归到本回合
    setTurns((ts) => [...ts, { id, question: text, answer: "", notices: [] }]);
    setInput("");
    setSending(true);
    setError(null);
    setProgress("对话：正在建立请求…");

    try {
      const resp = await fetch(`/sessions/${session.sid}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      if (!resp.ok) {
        const t = await resp.text();
        let d: unknown = t;
        try {
          d = JSON.parse(t).detail;
        } catch {
          /* 非 JSON 原样展示 */
        }
        throw new Error(`对话失败 HTTP ${resp.status}：${String(d)}`);
      }

      // ⚠️ 首字节被服务端的 `build_inventory` 阻塞（挂载 server，秒级）——
      //    立刻给出可解释的提示，而不是让界面看起来卡住（MVP 暴露的第一个真实可用性问题）
      setProgress("对话：正在准备工具面（首次挂载 server 需数秒）…");

      let n = 0;
      for await (const frame of readSse(resp)) {
        n += 1;
        const parsed = parseChatFrame(frame);
        if (parsed.kind === "malformed") {
          // ★ §8.4：降级为 incident 并可见，**不打断流**
          setError({
            message: `对话流中有结构不符的帧（event=${parsed.rawKind}）：${parsed.issues.join("；")}`,
            sig: "incident",
          });
          continue;
        }
        if (parsed.kind === "error") {
          setError({ message: `本轮失败：${parsed.detail}`, sig: "violated" });
        }
        setTurns((ts) => applyChatFrame(ts, id, parsed));
        setProgress(`对话：已收 ${n} 帧`);
      }
      setProgress(`对话完成：${n} 帧`);
    } catch (e) {
      setError({ message: (e as Error).message, sig: "violated" });
    } finally {
      setSending(false);
      session.setActiveTurn(null);
    }
  }, [input, session]);

  return (
    <section aria-label="对话分析" className="flex min-w-0 flex-1 flex-col">
      {error && <ErrorBanner sig={error.sig} message={error.message} />}

      <div ref={streamRef} className="flex-1 overflow-auto p-4">
        {!turns.length && (
          <div className="text-text-muted">
            问点什么开始研究 —— 例如「做一次基态潮流，把结果告诉我」。
          </div>
        )}

        {turns.map((t) => {
          // ★ 轨迹按**到达时的回合**分组（evidence 与 chat 是两条流，靠 turnId 对齐）
          const tools = session.rows.filter((r) => r.turnId === t.id);
          return (
            <div key={t.id} className="mb-4">
              <div className="mb-1 text-bodySm text-text-secondary">我</div>
              <div className="mb-2 whitespace-pre-wrap rounded-md bg-surface-sunken px-3 py-2">
                {t.question}
              </div>

              {!!tools.length && (
                <div
                  data-testid="tool-trail"
                  className="mb-2 rounded-md border border-border-subtle px-3 py-1.5"
                >
                  <div className="text-caption text-text-muted">
                    Tool Call（{tools.length}）
                  </div>
                  {tools.map((r) => (
                    <ToolCallRow
                      key={r.seq}
                      server={r.server}
                      tool={r.tool}
                      status={r.status}
                      args={r.args}
                      error={r.error}
                      results={r.results}
                    />
                  ))}
                </div>
              )}

              {!!t.notices.length && (
                <div className="mb-2 text-bodySm text-contract-degraded-fg">
                  {t.notices.map((n, i) => (
                    <div key={i}>▲ {n}</div>
                  ))}
                </div>
              )}

              <div className="mb-1 text-bodySm text-text-secondary">助手</div>
              <div className="whitespace-pre-wrap">
                {t.answer || (sending && t.id === nextTurnId.current - 1 ? "…" : "")}
              </div>

              {t.failure && (
                <div className="mt-1 text-bodySm text-contract-violated-fg">
                  ✖ 本轮未得出回答：{t.failure}
                </div>
              )}
            </div>
          );
        })}

        {!session.sid && <LoadingState label="正在建立会话…" />}
      </div>

      <div className="border-t border-border-subtle p-3">
        <div className="flex gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            placeholder="问点什么……（Enter 发送，Shift+Enter 换行）"
            className="min-w-0 flex-1"
            aria-label="对话输入"
          />
          <Button variant="primary" onClick={() => void send()} disabled={sending || !session.sid}>
            {sending ? "发送中…" : "发送"}
          </Button>
        </div>
        <div className="mt-1.5 flex flex-wrap gap-3 text-caption text-text-muted">
          <span>
            <span aria-hidden>{session.conn.ok ? "●" : "○"}</span> {session.conn.text}
          </span>
          {progress && <span>{progress}</span>}
        </div>
      </div>
    </section>
  );
}
