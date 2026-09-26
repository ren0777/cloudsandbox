"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ErrorBanner } from "@/components/ui";
import { api } from "@/lib/api";
import type { Draft, LabVersionRow, ScenarioOut } from "@/lib/builder";
import { fmtDate } from "@/lib/format";

const SCENARIO_LABEL: Record<string, string> = {
  empty: "Untouched sandbox", partial: "Partial solution", solution: "Reference solution",
};
const RUN_LABEL = { running: "Running", passed: "Passed", failed: "Failed", error: "Error" } as const;

export function TestPublishTab({ draft, dirty, onRun, onPublished }: {
  draft: Draft; dirty: boolean; onRun: () => Promise<void>; onPublished: (d: Draft) => void;
}) {
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<"test" | "publish" | null>(null);
  const t = draft.last_test;
  const current = draft.validation?.content_sha256 ?? null;
  const stale = !!t && t.status !== "running" && t.content_sha256 !== current;
  const canTest = draft.status !== "testing" && draft.status !== "published" && !!draft.validation?.ok;
  const canPublish = draft.status === "passed" && draft.tested_sha256 === current && !dirty;

  async function run() {
    setBusy("test"); setError(null);
    try { await onRun(); } catch (e) { setError(e); } finally { setBusy(null); }
  }
  async function publish() {
    setBusy("publish"); setError(null);
    try {
      const r = await api<{ draft: Draft }>(`/api/instructor/builder/drafts/${draft.id}/publish`, { method: "POST" });
      onPublished(r.draft);
    } catch (e) { setError(e); } finally { setBusy(null); }
  }

  return (
    <div className="stack" style={{ gap: 18 }}>
      <section className="stack">
        <h3>1 · Test in real sandboxes</h3>
        <p className="small muted" style={{ margin: 0 }}>Each scenario starts a fresh sandbox, runs the private script and grades it:
          the untouched sandbox must score 0, the reference solution full marks, and the partial solution (if any) its expected score.
          Every engine the lab may run on is tested. A run takes a few minutes.</p>
        <div className="row">
          <button className="primary" onClick={() => void run()} disabled={!canTest || busy !== null} data-testid="run-test">
            {draft.status === "testing" ? <><span className="spinner" /> Testing…</> : busy === "test" ? <><span className="spinner" /> Starting…</>
              : t ? "Run the test again" : "Run test"}</button>
          {!draft.validation?.ok && draft.status !== "published" && <span className="small muted">Fix the validation problems first.</span>}
          {dirty && canTest && <span className="small muted">Unsaved changes are saved first.</span>}
        </div>
        {t && <TestResult draft={draft} stale={stale} />}
      </section>

      <hr className="rule" style={{ margin: 0 }} />

      <section className="stack">
        <h3>2 · Publish</h3>
        {draft.status === "published" ? <Published draft={draft} /> : (
          <>
            <p className="small muted" style={{ margin: 0 }}>Publishing creates version <strong className="mono">{draft.content.lab.version}</strong> of
              <span className="mono"> {draft.slug}</span>. Published versions never change; it stays private to you until you share it.</p>
            <div className="row">
              <button className="primary" onClick={() => void publish()} disabled={!canPublish || busy !== null} data-testid="publish">
                {busy === "publish" ? <><span className="spinner" /> Publishing…</> : "Publish"}</button>
              {!canPublish && <span className="small muted">Needs a passing test of the current content.</span>}
            </div>
          </>
        )}
      </section>
      <ErrorBanner error={error} />
    </div>
  );
}

function TestResult({ draft, stale }: { draft: Draft; stale: boolean }) {
  const t = draft.last_test!;
  const cls = t.status === "passed" ? "pass" : t.status === "running" ? "info" : "fail";
  const pending = t.plan.filter((n) => !t.scenarios.some((s) => s.name === n));
  return (
    <div className="stack">
      <div className={`banner ${cls}`} role="status" aria-live="polite">
        {t.status === "running" && <span className="spinner" />}
        <div className="grow">
          <strong data-testid="test-status">{RUN_LABEL[t.status]}</strong>
          <span className="small"> · {t.status === "running" ? `${t.scenarios.length} of ${t.plan.length} scenarios done` : `finished ${fmtDate(t.finished_at)}`}</span>
          {t.error && <div className="small">{t.error}</div>}
        </div>
      </div>
      {stale && <div className="banner warn small"><div>The lab changed after this test. Run the test again before publishing.</div></div>}
      <table className="data">
        <thead><tr><th>Engine</th><th>Scenario</th><th>Expected</th><th>Score</th><th>Result</th></tr></thead>
        <tbody>
          {t.scenarios.map((s) => <ScenarioRow key={s.name} s={s} />)}
          {pending.map((n, i) => {
            const [eng, sc] = n.split("/");
            return (
              <tr key={n} className="muted">
                <td className="mono">{eng}</td><td>{SCENARIO_LABEL[sc] ?? sc}</td><td className="mono">{t.expected[sc]}</td>
                <td>—</td><td>{t.status === "running" && i === 0 ? <><span className="spinner" /> running</> : t.status === "running" ? "queued" : "not run"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ScenarioRow({ s }: { s: ScenarioOut }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <tr data-testid="scenario-row" data-scenario={s.name}>
        <td className="mono">{s.engine}</td>
        <td>{SCENARIO_LABEL[s.scenario] ?? s.scenario}</td>
        <td className="mono">{s.expected}</td>
        <td className="mono" data-testid="scenario-score">{s.actual ?? "—"}</td>
        <td>
          <span className={`pill ${s.ok ? "pass" : "fail"}`}>{s.ok ? "As expected" : "Mismatch"}</span>{" "}
          {s.tasks.length > 0 && <button className="small ghost" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? "Hide checks" : "Checks"}</button>}
          {!s.ok && s.detail && <div className="small" style={{ color: "var(--fail)", marginTop: 4 }}>{s.detail}</div>}
        </td>
      </tr>
      {open && (
        <tr><td colSpan={5} style={{ background: "#f7f9fc" }}>
          <table className="data lb-checks">
            <thead><tr><th>Task</th><th>Check</th><th>Marks</th><th>Expected</th><th>Actual</th><th /></tr></thead>
            <tbody>
              {s.tasks.flatMap((tk) => tk.checks.map((c, i) => (
                <tr key={`${tk.task_id}-${i}`}>
                  <td className="mono small">{i === 0 ? tk.task_id : ""}</td>
                  <td className="mono small">{c.check}{c.hidden && <span className="pill" style={{ marginLeft: 6 }}>hidden</span>}</td>
                  <td className="mono small">{c.marks_awarded} / {c.marks_possible}</td>
                  <td className="small">{String(c.expected ?? "")}</td>
                  <td className="small">{String(c.actual ?? "")}</td>
                  <td><span className={`pill ${c.passed ? "pass" : "fail"}`}>{c.passed ? "pass" : "fail"}</span></td>
                </tr>
              )))}
            </tbody>
          </table>
        </td></tr>
      )}
    </>
  );
}

function Published({ draft }: { draft: Draft }) {
  const router = useRouter();
  const [lv, setLv] = useState<LabVersionRow | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    void api<{ lab_versions: LabVersionRow[] }>("/api/instructor/lab-versions")
      .then((r) => setLv(r.lab_versions.find((v) => v.id === draft.published_version_id) ?? null)).catch(setError);
  }, [draft.published_version_id]);

  async function share(shared: boolean) {
    if (!lv) return;
    setError(null);
    try { await api(`/api/instructor/labs/${lv.lab_id}/share`, { method: "POST", body: { shared } }); setLv({ ...lv, shared }); } catch (e) { setError(e); }
  }
  async function nextVersion() {
    if (!lv) return;
    setBusy(true); setError(null);
    try {
      const d = await api<Draft>("/api/instructor/builder/drafts", { method: "POST", body: { source: "clone", lab_version_id: lv.id } });
      router.push(`/instructor/labs/drafts/${d.id}`);
    } catch (e) { setError(e); setBusy(false); }
  }
  return (
    <div className="stack">
      <div className="banner pass" data-testid="published-banner">
        <div className="grow">Published <strong className="mono">{draft.slug}@{draft.content.lab.version}</strong>. It can now be assigned in your courses.</div>
      </div>
      {lv && (
        <div className="row">
          {lv.mine && (
            <label className="row small" style={{ flexDirection: "row", gap: 6, fontWeight: 400 }}>
              <input type="checkbox" checked={lv.shared} style={{ width: "auto" }} onChange={(e) => void share(e.target.checked)} data-testid="publish-share" />
              Share with all instructors (they can assign and clone it)
            </label>
          )}
          <span className="grow" />
          <Link className="btn small" href="/instructor">Assign in a course</Link>
          <button className="small" onClick={() => void nextVersion()} disabled={busy}>Prepare next version</button>
        </div>
      )}
      <ErrorBanner error={error} />
    </div>
  );
}
