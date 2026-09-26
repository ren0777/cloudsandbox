"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Markdown } from "@/components/markdown";
import { Shell } from "@/components/shell";
import { ErrorBanner, ScoreRing } from "@/components/ui";
import { api, ApiError, capacityDelayMs } from "@/lib/api";
import { fmtDate, TRIGGER_LABEL } from "@/lib/format";
import type { AssignmentCard, LabSession } from "@/lib/types";

export default function LabBrief() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [a, setA] = useState<AssignmentCard | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [starting, setStarting] = useState(false);
  const [waiting, setWaiting] = useState<{ attempt: number; inUse?: number; max?: number } | null>(null);
  const cancelled = useRef(false);

  const load = useCallback(() => api<AssignmentCard>(`/api/assignments/${id}`).then(setA).catch(setError), [id]);
  useEffect(() => { void load(); return () => { cancelled.current = true; }; }, [load]);

  async function start() {
    cancelled.current = false;
    setStarting(true);
    setError(null);
    for (let attempt = 0; !cancelled.current; attempt++) {
      try {
        const s = await api<LabSession>(`/api/assignments/${id}/sessions`, { method: "POST" });
        router.push(`/labs/${id}/play?session=${s.id}`);
        return;
      } catch (e) {
        if (e instanceof ApiError && e.code === "capacity_full") {
          setWaiting({ attempt: attempt + 1, inUse: e.extra.in_use as number, max: e.extra.max as number });
          await new Promise((r) => setTimeout(r, capacityDelayMs(attempt)));
          continue;
        }
        if (e instanceof ApiError && e.code === "other_session_active") {
          setError(new ApiError(409, e.code, "You already have another lab running. Finish or end it first.",
            e.requestId, e.extra));
        } else setError(e);
        break;
      }
    }
    setWaiting(null);
    setStarting(false);
  }

  function cancelWaiting() {
    cancelled.current = true;
    setWaiting(null);
    setStarting(false);
  }

  if (!a) return <Shell><ErrorBanner error={error} onRetry={load} />{!error && <p className="muted">Loading…</p>}</Shell>;
  const lab = a.lab!;
  const active = a.active_session;
  const canStart = !!active || (a.is_open && a.attempts_left > 0);

  return (
    <Shell>
      <div className="brief">
        <section className="stack" style={{ gap: 18 }}>
          <div>
            <Link href="/labs" className="small">← My labs</Link>
            <div className="eyebrow" style={{ marginTop: 14 }}>{lab.services.map((s) => s.toUpperCase()).join(" · ")} · {lab.duration_minutes} min</div>
            <h1>{lab.title}</h1>
          </div>
          <div className="card"><Markdown text={lab.story} /></div>
          <div className="card">
            <h3 style={{ marginBottom: 10 }}>What you'll do</h3>
            <ol className="brief-tasks">
              {lab.tasks.map((t) => (
                <li key={t.id}><span>{t.title}</span><span className="mono muted">{Number(t.marks)} marks</span></li>
              ))}
            </ol>
          </div>
        </section>
        <aside className="stack">
          <div className="card stack">
            <div className="row">
              <ScoreRing score={a.final_score} max={a.max_score} />
              <div>
                <div className="small muted">{a.grade_policy === "best" ? "Best score counts" : "Latest score counts"}</div>
                <div className="score" style={{ fontSize: 22 }}>{a.final_score ?? "—"} <span className="muted small">/ {Number(a.max_score)}</span></div>
              </div>
            </div>
            <hr className="rule" style={{ margin: 0 }} />
            <dl className="facts">
              <dt>Due</dt><dd>{fmtDate(a.due_at)}</dd>
              <dt>Closes</dt><dd>{fmtDate(a.close_at)}</dd>
              <dt>Attempts</dt><dd>{a.attempts_used} of {a.attempts_allowed} used</dd>
            </dl>
            {waiting ? (
              <div className="banner info" role="status" aria-live="polite">
                <span className="spinner" />
                <div className="grow small">All lab seats are in use{waiting.max ? ` (${waiting.inUse}/${waiting.max})` : ""}. Retrying automatically…</div>
                <button className="small" onClick={cancelWaiting}>Cancel</button>
              </div>
            ) : (
              <button className="primary" disabled={!canStart || starting} onClick={() => void (active
                ? router.push(`/labs/${id}/play?session=${active.id}`) : start())} data-testid="start-lab">
                {starting ? <><span className="spinner" /> Starting…</> : active ? "Continue lab" : "Start lab"}
              </button>
            )}
            {!canStart && <p className="small muted" style={{ margin: 0 }}>
              {!a.is_open ? "This lab is closed." : "You've used all your attempts."}</p>}
            {a.is_late && a.is_open && !active && <p className="small" style={{ margin: 0, color: "var(--warn)" }}>
              The due date has passed. Attempts now are marked late.</p>}
            <ErrorBanner error={error} />
          </div>
          {a.attempts.length > 0 && (
            <div className="card">
              <h3 style={{ marginBottom: 8 }}>Attempts</h3>
              <table className="data">
                <tbody>
                  {a.attempts.map((t) => (
                    <tr key={t.id}>
                      <td><Link href={`/results/${t.id}`}>#{t.attempt_no}</Link></td>
                      <td className="small">{TRIGGER_LABEL[t.trigger]}{t.late ? " · late" : ""}{!t.counts ? " · not counted" : ""}</td>
                      <td className="score" style={{ textAlign: "right" }}>{t.score}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </aside>
      </div>
      <style>{`
        .brief { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 24px; align-items: start; }
        .brief-tasks { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 8px; }
        .brief-tasks li span:first-child { margin-right: 8px; }
        .brief-tasks li { padding-left: 4px; }
        .brief-tasks li .mono { font-size: 12px; }
        .facts { display: grid; grid-template-columns: auto 1fr; gap: 6px 14px; margin: 0; font-size: 14px; }
        .facts dt { color: var(--muted); } .facts dd { margin: 0; }
        @media (max-width: 860px) { .brief { grid-template-columns: 1fr; } }
      `}</style>
    </Shell>
  );
}
