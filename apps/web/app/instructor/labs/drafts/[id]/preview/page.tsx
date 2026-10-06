"use client";
// Interactive preview sandbox (phase 9 M42): the authored starting state in a real, isolated sandbox that
// the instructor can inspect in the AWS-style console and the browser terminal. It is NOT a student session:
// no attempt, grade, XP, badge or leaderboard event is ever created. Reset re-runs the declared typed
// break actions, so the broken state comes back identically.
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { CloudConsole } from "@/components/cloud-console";
import { Shell } from "@/components/shell";
import { Terminal } from "@/components/terminal";
import { ErrorBanner } from "@/components/ui";
import { api } from "@/lib/api";
import { type PreviewSandbox } from "@/lib/builder";
import { fmtDate } from "@/lib/format";

export default function PreviewSandboxPage() {
  const { id } = useParams<{ id: string }>();
  const [p, setP] = useState<PreviewSandbox | null>(null);
  const [tab, setTab] = useState<"console" | "terminal">("console");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const base = `/api/instructor/builder/drafts/${id}/preview-sandbox`;
  const load = useCallback(async () => {
    try { setP((await api<{ preview: PreviewSandbox }>(base)).preview); } catch (e) { setError(e); }
  }, [base]);
  useEffect(() => { void load(); }, [load]);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await fn(); await load(); } catch (e) { setError(e); } finally { setBusy(false); }
  }
  const start = () => act(() => api(base, { method: "POST" }));
  const reset = () => act(() => api(`${base}/reset`, { method: "POST" }));
  const stop = () => act(() => api(base, { method: "DELETE" }));

  const running = p?.status === "running" && !!p.sandbox_id;

  return (
    <Shell wide>
      <div className="stack" style={{ gap: 16 }}>
        <div className="row between" style={{ alignItems: "flex-end", flexWrap: "wrap" }}>
          <div>
            <Link href={`/instructor/labs/drafts/${id}`} className="small">← Back to the draft</Link>
            <div className="eyebrow" style={{ marginTop: 10 }}>Preview sandbox</div>
            <h1>Inspect the starting state</h1>
            <p className="muted small" style={{ margin: "6px 0 0", maxWidth: "70ch" }}>
              A real isolated sandbox built from this draft&apos;s declared state — the same sandbox a student
              lab gets. It is <strong>not</strong> a session: nothing here creates an attempt, grade, XP, badge
              or leaderboard event.
            </p>
          </div>
          <div className="row" style={{ gap: 8 }}>
            {running ? (
              <>
                <span className="pill pass" data-testid="preview-status">Running · {p?.engine}</span>
                <button onClick={() => void reset()} disabled={busy} data-testid="preview-reset">Reset</button>
                <button className="danger" onClick={() => void stop()} disabled={busy} data-testid="preview-stop">Stop</button>
              </>
            ) : (
              <>
                <span className="pill" data-testid="preview-status">Stopped</span>
                <button className="primary" onClick={() => void start()} disabled={busy} data-testid="preview-start">
                  {busy ? <><span className="spinner" /> Starting…</> : "Launch preview sandbox"}
                </button>
              </>
            )}
          </div>
        </div>
        <ErrorBanner error={error} />
        {p?.status === "stopped" && p.error && <div className="banner info small"><div>{p.error}</div></div>}

        {running ? (
          <>
            <div className="row" style={{ gap: 8, alignItems: "center" }}>
              <div className="lb-tabs" role="tablist" aria-label="Preview inspector">
                <button role="tab" aria-selected={tab === "console"} className={tab === "console" ? "on" : ""}
                  onClick={() => setTab("console")} data-testid="preview-tab-console">Console</button>
                <button role="tab" aria-selected={tab === "terminal"} className={tab === "terminal" ? "on" : ""}
                  onClick={() => setTab("terminal")} data-testid="preview-tab-terminal">Terminal</button>
              </div>
              <span className="spacer" style={{ flex: 1 }} />
              <span className="small muted">
                Started {fmtDate(p.started_at)}{p.last_active ? ` · last active ${fmtDate(p.last_active)}` : ""}
              </span>
            </div>
            {tab === "console"
              ? <CloudConsole sessionId={p.sandbox_id!} readOnly={false} />
              : <div className="terminal-wrap"><Terminal sessionId={p.sandbox_id!} active={tab === "terminal"} /></div>}
          </>
        ) : (
          <section className="card" style={{ margin: 0 }}>
            <h3 style={{ marginTop: 0 }}>Nothing running</h3>
            <p className="muted small" style={{ margin: "6px 0 0" }}>
              Launch the preview to inspect the sandbox the test run will see. Reset re-runs the declared
              starting state; Stop destroys the sandbox.
            </p>
          </section>
        )}
      </div>
      <style>{`
        .lb-tabs { display: flex; gap: 4px; flex-wrap: wrap; }
        .lb-tabs button { border-radius: 8px; }
        .lb-tabs button.on { background: var(--ink); color: #fff; border-color: var(--ink); }
        .terminal-wrap { height: 520px; border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
      `}</style>
    </Shell>
  );
}
