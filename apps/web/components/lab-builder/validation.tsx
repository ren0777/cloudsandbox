"use client";
import { type ErrorRow, rowLabel, type Validation } from "@/lib/builder";

/** Rows for a top-level field (loc = the field, or a path inside it). */
export function FieldErrors({ v, loc }: { v: Validation | null; loc: string }) {
  const rows = (v?.errors ?? []).filter((e) => !e.task && e.loc && (e.loc === loc || e.loc.startsWith(`${loc}.`)));
  return <ErrorList rows={rows} />;
}

export function ErrorList({ rows }: { rows: ErrorRow[] }) {
  if (!rows.length) return null;
  return (
    <ul className="lb-errs" role="list">
      {rows.map((e, i) => <li key={i}>{e.message}</li>)}
    </ul>
  );
}

/** The always-visible validation panel. Rows jump to the tab (and task) they belong to. */
export function ValidationPanel({ v, dirty, busy, onRevalidate, onJump }: {
  v: Validation | null; dirty: boolean; busy: boolean; onRevalidate: () => void; onJump: (row: ErrorRow) => void;
}) {
  const errors = v?.errors ?? [];
  return (
    <section className="card lb-validation" aria-labelledby="val-h" data-testid="validation-panel">
      <div className="row between">
        <h3 id="val-h">Validation</h3>
        <button className="small ghost" onClick={onRevalidate} disabled={busy}>{busy ? <span className="spinner" /> : "Re-check"}</button>
      </div>
      {dirty && <p className="small" style={{ color: "var(--warn)", margin: "6px 0 0" }}>Unsaved changes: this reflects the last save.</p>}
      {v?.ok ? (
        <div className="banner pass small" style={{ marginTop: 10 }} data-testid="validation-ok">
          <div>Valid. Ready for a test run.</div>
        </div>
      ) : (
        <>
          <p className="small muted" style={{ margin: "8px 0" }}>{errors.length} {errors.length === 1 ? "problem" : "problems"} to fix before testing:</p>
          <ol className="lb-val-list">
            {errors.map((e, i) => (
              <li key={i}>
                <button className="ghost lb-val-row" onClick={() => onJump(e)} data-testid="validation-row">
                  <span className="lb-val-where mono">{rowLabel(e)}</span>
                  <span>{e.message}</span>
                </button>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
