"use client";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { Markdown } from "@/components/markdown";
import { LiveArchitecture } from "@/components/architecture-diagram";
import { CloudConsole } from "@/components/cloud-console";
import { Shell } from "@/components/shell";
import { Terminal } from "@/components/terminal";
import { ErrorBanner } from "@/components/ui";
import { api, ApiError, newIdempotencyKey } from "@/lib/api";
import { FAILURE_TEXT, fmtDuration } from "@/lib/format";
import type { AttemptResult, LabSession, ResultView } from "@/lib/types";

const TRANSIENT = new Set(["REQUESTED", "PROVISIONING", "RESETTING", "SUBMITTING", "SUBMITTED", "TERMINATING"]);
const STEPS = ["Reserving a lab seat", "Creating your private network", "Starting your AWS simulator", "Opening your terminal"];

function Player() {
  const { id } = useParams<{ id: string }>();
  const sessionId = useSearchParams().get("session") ?? "";
  const router = useRouter();
  const [s, setS] = useState<LabSession | null>(null);
  const [skew, setSkew] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [tab, setTab] = useState<"console" | "terminal" | "diagram">("console");
  const [progress, setProgress] = useState<ResultView | null>(null);
  const [checking, setChecking] = useState(false);
  const [confirm, setConfirm] = useState<null | "submit" | "reset" | "stop">(null);
  const [acting, setActing] = useState<null | "submit" | "reset" | "stop">(null);
  const [error, setError] = useState<unknown>(null);
  const [openHints, setOpenHints] = useState<Record<string, number>>({}); // hints revealed per task
  const [showStory, setShowStory] = useState(true);
  const idemKey = useRef<string | null>(null);

  const load = useCallback(async () => {
    try {
      const x = await api<LabSession>(`/api/sessions/${sessionId}`);
      setSkew(new Date(x.server_time).getTime() - Date.now());
      setS(x);
      return x;
    } catch (e) { setError(e); return null; }
  }, [sessionId]);

  // Poll: fast while transient, slow while running (catches expiry / auto-submit).
  useEffect(() => {
    let t: ReturnType<typeof setTimeout>;
    let stop = false;
    const tick = async () => {
      const x = await load();
      if (stop) return;
      t = setTimeout(tick, x && TRANSIENT.has(x.state) ? 1200 : 15000);
    };
    void tick();
    return () => { stop = true; clearTimeout(t); };
  }, [load]);

  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);

  // Heartbeat while visible and running (PLAN §4).
  const heartbeat = useCallback(() => api(`/api/sessions/${sessionId}/heartbeat`, { method: "POST" })
    .then(() => load()).catch(() => undefined), [sessionId, load]);
  useEffect(() => {
    if (s?.state !== "READY") return;
    const t = setInterval(() => { if (document.visibilityState === "visible") void heartbeat(); }, 60000);
    return () => clearInterval(t);
  }, [s?.state, heartbeat]);

  // Leave the player once an attempt exists (explicit or automatic submission).
  useEffect(() => {
    if (s?.attempt_id && (s.state === "SUBMITTED" || s.state === "TERMINATING" || s.state === "TERMINATED") && !acting) {
      router.replace(`/results/${s.attempt_id}?auto=1`);
    }
  }, [s, acting, router]);

  async function check() {
    setChecking(true);
    setError(null);
    try { setProgress(await api<ResultView>(`/api/sessions/${sessionId}/progress`, { method: "POST" })); }
    catch (e) { setError(e); }
    finally { setChecking(false); }
  }

  async function act(kind: "submit" | "reset" | "stop") {
    setConfirm(null);
    setActing(kind);
    setError(null);
    idemKey.current ??= newIdempotencyKey(); // same key if the student retries after a network error
    try {
      if (kind === "submit") {
        const r = await api<AttemptResult>(`/api/sessions/${sessionId}/submit`,
          { method: "POST", headers: { "Idempotency-Key": idemKey.current } });
        router.replace(`/results/${r.attempt.id}`);
        return;
      }
      if (kind === "reset") {
        await api(`/api/sessions/${sessionId}/reset`, { method: "POST", headers: { "Idempotency-Key": idemKey.current } });
        setProgress(null);
      } else {
        await api(`/api/sessions/${sessionId}/stop`, { method: "POST" });
        router.replace(`/labs/${id}`);
        return;
      }
      idemKey.current = null;
      await load();
    } catch (e) {
      if (e instanceof ApiError && e.code === "already_submitted" && e.extra.attempt_id) {
        router.replace(`/results/${e.extra.attempt_id}`);
        return;
      }
      if (e instanceof ApiError && e.status < 500) idemKey.current = null;
      setError(e);
      await load();
    } finally {
      setActing(null);
    }
  }

  async function restart() {
    try {
      const x = await api<LabSession>(`/api/assignments/${id}/sessions`, { method: "POST" });
      router.replace(`/labs/${id}/play?session=${x.id}`);
      setS(null);
      setProgress(null);
    } catch (e) { setError(e); }
  }

  if (!s) return <Shell><ErrorBanner error={error} onRetry={load} />{!error && <p className="muted">Opening your lab…</p>}</Shell>;
  const lab = s.lab!;
  const serverNow = now + skew;
  const left = s.expires_at ? new Date(s.expires_at).getTime() - serverNow : null;
  const idleWarn = s.state === "READY" && s.idle_warning_at && serverNow >= new Date(s.idle_warning_at).getTime();
  const idleLeft = s.idle_deadline_at ? new Date(s.idle_deadline_at).getTime() - serverNow : 0;
  const ready = s.state === "READY";
  const byTask = new Map(progress?.tasks.map((t) => [t.task_id, t]));
  const provisioningStep = s.state === "REQUESTED" ? 0 : s.state === "PROVISIONING"
    ? Math.min(3, 1 + Math.floor((serverNow - new Date(s.created_at).getTime()) / 4000)) : 4;

  return (
    <Shell wide>
      <div className="player">
        <div className="player-bar">
          <div className="grow" style={{ minWidth: 0 }}>
            <Link href={`/labs/${id}`} className="small">← Lab brief</Link>
            <h1 className="player-title">{lab.title}</h1>
          </div>
          <span className={`pill ${ready ? "pass" : s.state === "FAILED" ? "fail" : "info"}`} data-testid="session-state">
            {ready ? "Running" : s.state === "FAILED" ? "Stopped" : s.state.charAt(0) + s.state.slice(1).toLowerCase() + "…"}
          </span>
          {left !== null && ready && (
            <span className={`timer mono ${left < 5 * 60000 ? "low" : ""}`} aria-label="Time left" title="Time left">⏱ {fmtDuration(left)}</span>
          )}
          <button onClick={() => void check()} disabled={!ready || checking} data-testid="check-progress">
            {checking ? <><span className="spinner" /> Checking…</> : "Check progress"}
          </button>
          <button onClick={() => setConfirm("reset")} disabled={!ready || !!acting}>Reset lab</button>
          <button onClick={() => setConfirm("stop")} disabled={!ready || !!acting} className="danger">End lab</button>
          <button className="primary" onClick={() => setConfirm("submit")} disabled={!ready || !!acting} data-testid="submit-lab">
            {acting === "submit" ? <><span className="spinner" /> Grading…</> : "Submit for grading"}
          </button>
        </div>

        {idleWarn && (
          <div className="banner warn player-banner" role="alert">
            <div className="grow">You've been inactive. Your lab will be submitted automatically in {fmtDuration(idleLeft)}.</div>
            <button className="small" onClick={() => void heartbeat()}>I'm still here</button>
          </div>
        )}
        {error ? <div className="player-banner"><ErrorBanner error={error} /></div> : null}

        <div className="player-body">
          <aside className="mission" aria-label="Tasks">
            <button className="ghost small story-toggle" onClick={() => setShowStory(!showStory)} aria-expanded={showStory}>
              {showStory ? "Hide briefing" : "Show briefing"}
            </button>
            {lab.kind === "break_fix" && (
              <div className="banner warn small" style={{ marginBottom: 10 }} data-testid="breakfix-banner">
                <div><strong>Break-fix lab.</strong> Your environment starts broken on purpose. Find what&apos;s wrong and repair it.
                  <strong> Reset lab</strong> restores the original broken state.</div></div>)}
            {showStory && <div className="story small"><Markdown text={lab.story} /></div>}
            <div className="row between" style={{ margin: "14px 0 8px" }}>
              <span className="eyebrow">Checklist</span>
              {progress && <span className="score" data-testid="progress-score">{progress.score} / {Number(progress.max_score)}</span>}
            </div>
            <ol className="stubs">
              {lab.tasks.map((t) => {
                const r = byTask.get(t.id);
                const stateCls = !r ? "" : r.passed ? "done" : "todo";
                return (
                  <li key={t.id} className={`stub ${stateCls}`} data-testid={`task-${t.id}`}>
                    <div className="stub-main">
                      <span className="stub-mark" aria-hidden>{!r ? "" : r.passed ? "✓" : "•"}</span>
                      <div className="grow">
                        <div className="stub-title">{t.title}</div>
                        {t.description && <div className="small muted">{t.description}</div>}
                        {r && r.checks.filter((c) => !c.passed).map((c, i) => (
                          <div key={i} className="small stub-miss">{c.message}</div>
                        ))}
                        {(openHints[t.id] ?? 0) > 0 && (
                          <ol className="hints small">
                            {t.hints.slice(0, openHints[t.id]).map((h, i) => <li key={i}><Markdown text={h} /></li>)}
                          </ol>
                        )}
                        {(openHints[t.id] ?? 0) < t.hints.length && (
                          <button className="ghost small hint-btn" data-testid={`hint-${t.id}`}
                            onClick={() => setOpenHints({ ...openHints, [t.id]: (openHints[t.id] ?? 0) + 1 })}>
                            {(openHints[t.id] ?? 0) === 0 ? "Show a hint" : `Next hint (${(openHints[t.id] ?? 0) + 1} of ${t.hints.length})`}
                          </button>
                        )}
                      </div>
                    </div>
                    <div className="stub-marks" aria-label={`${r ? r.marks_awarded : 0} of ${Number(t.marks)} marks`}>
                      <span className="score">{r ? Number(r.marks_awarded) : "–"}</span>
                      <span className="small muted">/{Number(t.marks)}</span>
                    </div>
                  </li>
                );
              })}
            </ol>
            <p className="small muted" style={{ marginTop: 10 }}>
              Checking progress doesn't use an attempt. Submitting grades your lab and ends it.
            </p>
          </aside>

          <section className="workspace">
            {s.state === "FAILED" ? (
              <div className="card stack" style={{ maxWidth: 520, margin: "40px auto" }}>
                <h2>{FAILURE_TEXT[s.failure_reason ?? ""] ?? "Your lab stopped."}</h2>
                <p className="muted" style={{ margin: 0 }}>
                  {s.failure_reason === "grading_failed" ? "Start the lab again to retry." : "Your attempts are unaffected. Start a fresh sandbox to continue."}
                </p>
                <div><button className="primary" onClick={() => void restart()}>Restart lab</button></div>
              </div>
            ) : !ready && provisioningStep < 4 ? (
              <div className="card stack provision" role="status" aria-live="polite">
                <h2>Setting up your lab</h2>
                <ol className="steps">
                  {STEPS.map((label, i) => (
                    <li key={label} className={i < provisioningStep ? "done" : i === provisioningStep ? "now" : ""}>
                      {i < provisioningStep ? "✓" : i === provisioningStep ? <span className="spinner" /> : "○"} {label}
                    </li>
                  ))}
                </ol>
                <p className="small muted" style={{ margin: 0 }}>This usually takes about 10 seconds.</p>
              </div>
            ) : (
              <>
                <div className="tabs-top" role="tablist">
                  <button role="tab" aria-selected={tab === "console"} className={tab === "console" ? "on" : ""} onClick={() => setTab("console")}>Console</button>
                  <button role="tab" aria-selected={tab === "terminal"} className={tab === "terminal" ? "on" : ""} onClick={() => setTab("terminal")} data-testid="tab-terminal">AWS CLI</button>
                  <button role="tab" aria-selected={tab === "diagram"} className={tab === "diagram" ? "on" : ""} onClick={() => setTab("diagram")} data-testid="tab-diagram">Architecture</button>
                  <span className="grow" />
                  {!ready && <span className="small muted"><span className="spinner" /> {s.state === "RESETTING" ? "Resetting your sandbox…" : "Working…"}</span>}
                </div>
                <div className="panes">
                  <div className="pane" hidden={tab !== "console"}><CloudConsole sessionId={s.id} readOnly={!ready} initial={lab.services[0] ?? "s3"} /></div>
                  <div className="pane" hidden={tab !== "terminal"}><Terminal sessionId={s.id} active={ready} /></div>
                  <div className="pane pane-scroll" hidden={tab !== "diagram"}>{tab === "diagram" && <LiveArchitecture sessionId={s.id} active={ready} />}</div>
                </div>
              </>
            )}
          </section>
        </div>
      </div>

      {confirm && (
        <div className="dialog-backdrop" role="dialog" aria-modal aria-labelledby="dlg-title" onClick={() => setConfirm(null)}>
          <div className="dialog stack" onClick={(e) => e.stopPropagation()}>
            <h2 id="dlg-title">{confirm === "submit" ? "Submit for grading?" : confirm === "reset" ? "Reset this lab?" : "End this lab?"}</h2>
            <p className="muted" style={{ margin: 0 }}>
              {confirm === "submit" ? "Your sandbox is locked, graded and then removed. This uses one attempt."
                : confirm === "reset" ? "Everything in your sandbox is deleted and you start from a clean slate. This doesn't use an attempt."
                : "Your sandbox is removed without grading. This doesn't use an attempt."}
            </p>
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <button onClick={() => setConfirm(null)} autoFocus>Cancel</button>
              <button className={confirm === "submit" ? "primary" : "danger"} onClick={() => void act(confirm)} data-testid="confirm-action">
                {confirm === "submit" ? "Submit" : confirm === "reset" ? "Reset lab" : "End lab"}
              </button>
            </div>
          </div>
        </div>
      )}

      <style>{`
        .player { height: calc(100vh - 52px); display: flex; flex-direction: column; }
        .player-bar { display: flex; align-items: center; gap: 10px; padding: 10px 20px; background: var(--panel); border-bottom: 1px solid var(--line); flex-wrap: wrap; }
        .player-title { font-size: 20px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .timer { font-size: 15px; padding: 6px 10px; border-radius: 8px; background: #eef2f8; }
        .timer.low { background: var(--warn-soft); color: var(--warn); }
        .player-banner { margin: 10px 20px 0; }
        .player-body { flex: 1; min-height: 0; display: grid; grid-template-columns: 360px minmax(0, 1fr); }
        .mission { border-right: 1px solid var(--line); padding: 14px 16px; overflow: auto; background: #fbfcfe; }
        .story { background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 12px; }
        .story-toggle { padding-left: 0; }
        .stubs { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
        .stub { display: grid; grid-template-columns: 1fr 64px; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; transition: border-color .3s, background .3s; }
        .stub-main { display: flex; gap: 10px; padding: 12px; }
        .stub-mark { width: 22px; height: 22px; border-radius: 50%; border: 2px solid var(--line); display: grid; place-items: center; font-size: 12px; font-weight: 700; flex: none; margin-top: 1px; }
        .stub-title { font-weight: 600; word-break: break-word; }
        .stub-marks { border-left: 2px dashed var(--line); display: flex; flex-direction: column; align-items: center; justify-content: center; background: #f7f9fc; }
        .stub-marks .score { font-size: 20px; }
        .stub.done { border-color: #a9dcc3; }
        .stub.done .stub-mark { background: var(--pass); border-color: var(--pass); color: #fff; animation: pop .35s ease-out; }
        .stub.done .stub-marks { background: var(--pass-soft); color: var(--pass); }
        .stub.todo .stub-mark { border-color: #f0c5c8; color: var(--fail); }
        .stub-miss { color: var(--fail); margin-top: 4px; }
        .hint-btn { padding: 4px 0; margin-top: 4px; color: var(--signal-strong); }
        .hints { margin: 4px 0 0; padding-left: 18px; color: var(--ink-2); }
        @keyframes pop { 0% { transform: scale(.4); } 70% { transform: scale(1.15); } 100% { transform: scale(1); } }
        .workspace { padding: 12px 16px 16px; display: flex; flex-direction: column; min-height: 0; }
        .tabs-top { display: flex; gap: 4px; margin-bottom: 8px; align-items: center; }
        .tabs-top button { border-radius: 8px; }
        .tabs-top button.on { background: var(--ink); color: #fff; border-color: var(--ink); }
        .panes { flex: 1; min-height: 0; }
        .pane { height: 100%; }
        .pane[hidden] { display: none; }
        .pane-scroll { overflow: auto; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); padding: 14px; }
        .provision { max-width: 460px; margin: 60px auto; }
        .steps { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 10px; }
        .steps li { color: var(--muted); display: flex; gap: 8px; align-items: center; }
        .steps li.done { color: var(--pass); } .steps li.now { color: var(--ink); font-weight: 600; }
        @media (max-width: 900px) {
          .player { height: auto; }
          .player-body { grid-template-columns: 1fr; }
          .mission { border-right: 0; border-bottom: 1px solid var(--line); }
          .pane { height: 70vh; }
        }
      `}</style>
    </Shell>
  );
}

export default function PlayPage() {
  return <Suspense><Player /></Suspense>;
}
