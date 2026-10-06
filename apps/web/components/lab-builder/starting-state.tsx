"use client";
// Starting state (phase 9, milestone 41): a break-fix lab's broken environment is built from typed break
// actions, never from instructor-written shell. The API compiles these actions into the setup each student
// gets; this tab edits the actions, the expected baseline score and shows the Broken State Summary.
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { type BreakAction, defaultParams, type JsonSchema, type Lab, maxScore, type Validation } from "@/lib/builder";
import { SchemaForm } from "@/components/schema-form";
import { ErrorList } from "./validation";

type ActionDef = { type: string; service: string; params_schema: JsonSchema };
type Summary = { lines: { type: string; service: string; summary: string }[]; errors: string[] };

const paramsOf = (a: BreakAction) => Object.fromEntries(Object.entries(a).filter(([k]) => k !== "type"));

export function StartingStateTab({ lab, draftId, validation, onChange }: {
  lab: Lab; draftId: string; validation: Validation | null; onChange: (lab: Lab) => void;
}) {
  const [defs, setDefs] = useState<ActionDef[] | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<unknown>(null);
  const actions = lab.break_actions ?? [];
  const isBreakFix = lab.kind === "break_fix";
  const full = maxScore(lab);
  const expected = lab.baseline?.expected_score ?? 0;

  useEffect(() => {
    api<{ break_actions: ActionDef[] }>("/api/instructor/builder/break-actions")
      .then((r) => setDefs(r.break_actions)).catch(setError);
  }, []);

  // Broken State Summary: derived by the API from the same action definitions the compiler uses.
  useEffect(() => {
    if (!isBreakFix) { setSummary(null); return; }
    const t = setTimeout(() => {
      api<Summary>("/api/instructor/builder/break-actions/summary", { method: "POST", body: { lab } })
        .then(setSummary).catch(setError);
    }, 400);
    return () => clearTimeout(t);
  }, [lab, isBreakFix]);

  const set = (next: BreakAction[]) => onChange({ ...lab, break_actions: next });
  const services = [...new Set((defs ?? []).map((d) => d.service))].sort();
  const errorsFor = (i: number) => (validation?.errors ?? []).filter((e) => e.break_action === i);

  function add() {
    const d = defs?.[0];
    if (d) set([...actions, { type: d.type, ...defaultParams(d.params_schema) }]);
  }
  function changeType(i: number, type: string) {
    const d = defs?.find((x) => x.type === type);
    if (d) set(actions.map((a, j) => (j === i ? { type, ...defaultParams(d.params_schema) } : a)));
  }
  function move(i: number, by: number) {
    const next = [...actions];
    const [a] = next.splice(i, 1);
    next.splice(i + by, 0, a);
    set(next);
  }

  if (!isBreakFix) {
    return (
      <div className="stack" style={{ gap: 14 }}>
        <h3 style={{ margin: 0 }}>Starting state</h3>
        <p className="muted" style={{ margin: 0 }}>
          This is a <strong>guided</strong> lab: students start from an empty sandbox. A <strong>break-fix</strong> lab
          starts from a broken environment that students repair. The broken state is built from safe, typed actions —
          you never write shell, and <em>Reset</em> always recreates it.
        </p>
        <div>
          <button className="primary" data-testid="make-break-fix"
            onClick={() => onChange({ ...lab, kind: "break_fix", break_actions: [] })}>
            Make this a break-fix lab
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="stack" style={{ gap: 14 }}>
      <div className="row between">
        <div>
          <h3 style={{ margin: 0 }}>Starting state</h3>
          <p className="small muted" style={{ margin: "4px 0 0" }}>
            Each action below is compiled into the setup for every student. Reset recreates exactly this state.
          </p>
        </div>
        {!lab.setup && (
          <button className="small ghost" data-testid="make-guided"
            onClick={() => onChange({ ...lab, kind: "guided", break_actions: undefined, baseline: undefined } as Lab)}>
            Convert to a guided lab
          </button>
        )}
      </div>

      {lab.setup && (
        <div className="banner info small"><div>
          This lab uses a legacy <span className="mono">setup</span> script (carried read-only from a clone or import).
          Break actions are the supported way to author starting states; a new lab starts cleanly from actions.
        </div></div>
      )}

      {!lab.setup && (
        <>
          <label style={{ maxWidth: 320 }}>
            Expected starting score
            <input type="number" min={0} max={Math.max(0, full - 0.01)} step="0.01" data-testid="baseline-score"
              value={String(expected)} disabled={full === 0}
              onChange={(e) => onChange({ ...lab, baseline: { expected_score: Number(e.target.value || 0) } })} />
            <span className="small muted">
              The broken state usually scores 0. If your lab intentionally starts partly correct, set the score the
              baseline should earn (below full marks, {full}). The test run must match it exactly.
            </span>
          </label>

          <div className="stack" style={{ gap: 10 }}>
            {actions.map((a, i) => {
              const def = defs?.find((d) => d.type === a.type);
              return (
                <div className="card" key={i} data-testid="break-action" style={{ margin: 0 }}>
                  <div className="row between">
                    <select value={a.type} onChange={(e) => changeType(i, e.target.value)} data-testid="break-action-type"
                      style={{ maxWidth: 340 }}>
                      {services.map((svc) => (
                        <optgroup key={svc} label={svc}>
                          {(defs ?? []).filter((d) => d.service === svc)
                            .map((d) => <option key={d.type} value={d.type}>{d.type}</option>)}
                        </optgroup>
                      ))}
                    </select>
                    <div className="row" style={{ gap: 4 }}>
                      <button type="button" className="small ghost" disabled={i === 0} aria-label="Move up"
                        onClick={() => move(i, -1)}>↑</button>
                      <button type="button" className="small ghost" disabled={i === actions.length - 1} aria-label="Move down"
                        onClick={() => move(i, 1)}>↓</button>
                      <button type="button" className="small ghost danger" data-testid="break-action-remove"
                        onClick={() => set(actions.filter((_, j) => j !== i))}>Remove</button>
                    </div>
                  </div>
                  {def
                    ? <SchemaForm schema={def.params_schema} value={paramsOf(a)} idPrefix={`ba-${i}`}
                        onChange={(p) => set(actions.map((x, j) => (j === i ? { type: a.type, ...p } : x)))} />
                    : <p className="small muted" style={{ margin: 0 }}>Loading the action form…</p>}
                  <ErrorList rows={errorsFor(i)} />
                </div>
              );
            })}
            <div>
              <button type="button" className="small" onClick={add} disabled={!defs?.length} data-testid="add-break-action">
                + Add break action
              </button>
            </div>
          </div>

          <section className="card" style={{ margin: 0 }} data-testid="broken-state">
            <h4 style={{ margin: "0 0 6px" }}>Broken State Summary</h4>
            {summary?.errors.length ? <ErrorList rows={summary.errors.map((message) => ({
              message, loc: null, task: null, check: null, field: null }))} />
              : (
                <ul className="stack" style={{ gap: 4, listStyle: "none", padding: 0, margin: 0 }}>
                  {(summary?.lines ?? []).map((l, i) => (
                    <li key={i} className="row" style={{ gap: 8 }}>
                      <span className="pill warn" aria-hidden>⚠</span>
                      <span>{l.summary}</span>
                      <span className="small muted mono">{l.service}</span>
                    </li>
                  ))}
                  {summary && summary.lines.length === 0 && <li className="muted">No actions yet.</li>}
                </ul>
              )}
            <p className="small muted" style={{ margin: "10px 0 0" }}>
              On <strong>Test &amp; publish</strong>, the untouched sandbox must score <strong>{String(expected)}</strong>
              {" "}and the reference solution must score <strong>{full}</strong>. The run also resets the sandbox and
              checks the baseline comes back identically.
            </p>
          </section>
        </>
      )}
      <p className="small muted" style={{ margin: 0 }}>
        Preview the broken sandbox interactively in the console and terminal, then run the baseline on the
        Test tab.{" "}
        <Link href={`/instructor/labs/drafts/${draftId}/preview`} data-testid="open-preview-sandbox">
          Launch preview sandbox →
        </Link>
      </p>
    </div>
  );
}
