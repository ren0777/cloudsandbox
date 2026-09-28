"use client";
import { useState } from "react";
import { ErrorBanner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { CheckRun, ErrorRow } from "@/lib/builder";
import { ErrorList } from "./validation";

const show = (v: unknown) =>
  v === undefined || v === null ? "—" : typeof v === "string" ? v : JSON.stringify(v);

/** Run a single grading check against this draft's preview sandbox (M47) and show exactly what the grader
 * would see. Nothing is stored: no attempt, grade, XP, badge or evidence row. */
export function RunCheck({ draftId, taskId, index, previewRunning }: {
  draftId: string; taskId: string; index: number; previewRunning: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [out, setOut] = useState<CheckRun | null>(null);
  const [error, setError] = useState<unknown>(null);

  async function run() {
    setBusy(true); setError(null); setOut(null);
    try {
      setOut(await api<CheckRun>(`/api/instructor/builder/drafts/${draftId}/preview-sandbox/check`,
        { method: "POST", body: { task: taskId, check: index } }));
    } catch (e) { setError(e); } finally { setBusy(false); }
  }

  return (
    <div className="lb-run-wrap">
      <div className="row" style={{ alignItems: "center", gap: 8 }}>
        <button className="small" onClick={() => void run()} disabled={!previewRunning || busy}
          data-testid="run-check" title={previewRunning ? "Run it against the preview sandbox"
            : "Start the preview sandbox first"}>
          {busy ? <><span className="spinner" /> Running…</> : "Run this check"}
        </button>
        {!previewRunning && (
          <span className="small muted" data-testid="run-check-hint">Start the preview sandbox to run this
            check against the starting state.</span>
        )}
      </div>
      <ErrorBanner error={error} />
      {error instanceof ApiError && (
        <ErrorList rows={(error.extra.errors as ErrorRow[] | undefined) ?? []} />
      )}
      {out?.status === "ran" && (
        <div className={`lb-run ${out.passed ? "ok" : "no"}`} data-testid="check-run-result" data-passed={out.passed}>
          <div className="row between">
            <strong>{out.passed ? "Passed" : "Failed"} <span className="small" style={{ fontWeight: 400 }}>
              · {out.check.type}</span></strong>
            <span className="small">{out.check.marks_possible} marks possible</span>
          </div>
          <dl className="lb-run-grid">
            <dt>Expected</dt><dd className="mono" data-testid="run-expected">{show(out.expected)}</dd>
            <dt>Actual</dt><dd className="mono" data-testid="run-actual">{show(out.actual)}</dd>
          </dl>
          <p className="small" style={{ margin: 0 }} data-testid="run-message">{out.message}</p>
          <p className="small muted" style={{ margin: 0 }}>From the preview sandbox ({out.engine}). Grading
            uses the same check and the same evidence, on the student&apos;s own sandbox.</p>
        </div>
      )}
      {out?.status === "blocked" && (
        <div className="lb-run blocked" data-testid="check-run-blocked">
          <div className="row between">
            <strong>Cannot run <span className="small" style={{ fontWeight: 400 }}>· {out.check}</span></strong>
            <span className="small mono">{out.reason.code}</span>
          </div>
          <p className="small" style={{ margin: 0 }} data-testid="run-blocked-message">{out.reason.message}</p>
          {out.reason.operation && <p className="small muted" style={{ margin: 0 }}>
            Operation {out.reason.operation} is not declared usable for this lab&apos;s engine.</p>}
        </div>
      )}
      <style>{`
        .lb-run-wrap { margin-top: 8px; display: flex; flex-direction: column; gap: 8px; }
        .lb-run { border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; }
        .lb-run.ok { background: var(--pass-soft); border-color: #bfe6d2; }
        .lb-run.no { background: var(--fail-soft); border-color: #f0c5c8; }
        .lb-run.blocked { background: var(--warn-soft); border-color: #f0d9a4; }
        .lb-run-grid { display: grid; grid-template-columns: max-content 1fr; gap: 2px 12px; margin: 8px 0; }
        .lb-run-grid dt { font-size: 12px; font-weight: 650; color: var(--muted); }
        .lb-run-grid dd { margin: 0; font-size: 13px; word-break: break-word; }
      `}</style>
    </div>
  );
}
