"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Shell } from "@/components/shell";
import { ErrorBanner } from "@/components/ui";
import { api } from "@/lib/api";

// Course analytics (M49): every figure below is computed from stored attempts and task results, and an
// infrastructure interruption is always shown on its own — never folded into a student's score.
type Row = {
  assignment_id: string; title: string; lab_title: string; max_score: string;
  students: number; submitted: number; submission_rate: number; attempts: number;
  avg_attempts_used: string | null; avg_score: string | null; avg_completion_minutes: number | null;
  late_submissions: number; interruptions: number; interruption_reasons: Record<string, number>;
};
type Ranked = { assignment_id: string; assignment_title: string; task_id: string; task_title: string;
  check?: string; attempts: number; failed: number; failure_rate: number };
type Stats = {
  course: { id: string; code: string; title: string };
  totals: { students: number; assignments: number; submissions: number; submission_rate: number;
    late_submissions: number; interruptions: number; avg_score: string | null };
  assignments: Row[]; most_failed_tasks: Ranked[]; most_missed_checks: Ranked[];
};

const pct = (v: number) => `${Math.round(v * 100)}%`;
const m = (v: number | null) => (v === null ? "—" : `${v} min`);

function Stat({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "warn" | "fail" }) {
  return (
    <div className="card flat stat" data-testid="stat">
      <div className="eyebrow">{label}</div>
      <div className="stat-value" style={tone ? { color: `var(--${tone})` } : undefined} data-testid={`stat-${label.toLowerCase().replace(/\s+/g, "-")}`}>{value}</div>
      {hint && <div className="small muted">{hint}</div>}
    </div>
  );
}

export default function Analytics() {
  const { id } = useParams<{ id: string }>();
  const [s, setS] = useState<Stats | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(() => api<Stats>(`/api/instructor/courses/${id}/analytics`).then(setS).catch(setError), [id]);
  useEffect(() => { void load(); }, [load]);

  if (!s) return <Shell><ErrorBanner error={error} onRetry={load} />{!error && <p className="muted">Crunching the numbers…</p>}</Shell>;
  const t = s.totals;
  const empty = t.assignments === 0;

  return (
    <Shell wide>
      <main className="page" style={{ maxWidth: 1400 }}>
        <div className="stack" style={{ gap: 18 }}>
          <Link href={`/instructor/courses/${id}`} className="small">← {s.course.code}</Link>
          <div className="row between">
            <div>
              <div className="eyebrow">Analytics · {t.students} students · {t.assignments} {t.assignments === 1 ? "lab" : "labs"}</div>
              <h1>{s.course.code} · {s.course.title}</h1>
            </div>
            <div className="row" style={{ gap: 8 }}>
              <button className="small" onClick={() => void load()}>Refresh</button>
              {!empty && <a className="btn small" href={`/api/instructor/courses/${id}/analytics.csv`} data-testid="export-analytics">Export CSV</a>}
            </div>
          </div>
          <ErrorBanner error={error} />

          {empty ? (
            <div className="card flat muted" data-testid="analytics-empty">
              No labs assigned to this course yet — assign one and the numbers will appear here.
            </div>
          ) : (
            <>
              <div className="stats">
                <Stat label="Students" value={String(t.students)} />
                <Stat label="Submitted" value={String(t.submissions)}
                  hint={`${pct(t.submission_rate)} of expected submissions`} />
                <Stat label="Average score" value={t.avg_score ?? "—"}
                  hint={t.avg_score ? "across submitted students" : "nobody has submitted yet"} />
                <Stat label="Late" value={String(t.late_submissions)}
                  tone={t.late_submissions ? "warn" : undefined} hint="counted attempts after the due date" />
                <Stat label="Interrupted" value={String(t.interruptions)}
                  tone={t.interruptions ? "fail" : undefined}
                  hint="platform failures — not student mistakes" />
              </div>

              <section className="card" data-testid="analytics-assignments">
                <h2>By assignment</h2>
                {s.assignments.every((a) => a.submitted === 0) && (
                  <p className="small muted" data-testid="no-submissions">Nobody has submitted yet — the
                    assignments below are what the class has to work with.</p>
                )}
                <table className="data">
                    <thead><tr>
                      <th>Assignment</th><th>Submitted</th><th>Avg score</th><th>Avg attempts</th>
                      <th>Avg time</th><th>Late</th><th>Interrupted</th>
                    </tr></thead>
                    <tbody>
                      {s.assignments.map((a) => (
                        <tr key={a.assignment_id} data-testid="assignment-stat">
                          <td><Link href={`/instructor/assignments/${a.assignment_id}`}>{a.title}</Link>
                            <div className="small muted">{a.lab_title} · out of {Number(a.max_score)}</div></td>
                          <td>{a.submitted}/{a.students}<div className="small muted">{pct(a.submission_rate)}</div></td>
                          <td className="score">{a.avg_score ?? "—"}</td>
                          <td>{a.avg_attempts_used ?? "—"}</td>
                          <td>{m(a.avg_completion_minutes)}</td>
                          <td style={a.late_submissions ? { color: "var(--warn)" } : undefined}>{a.late_submissions}</td>
                          <td style={a.interruptions ? { color: "var(--fail)" } : undefined}>
                            {a.interruptions}
                            {a.interruptions > 0 && (
                              <div className="small muted">{Object.entries(a.interruption_reasons)
                                .map(([k, v]) => `${k} ×${v}`).join(", ")}</div>)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
              </section>

              <div className="two">
                <section className="card" data-testid="most-failed-tasks">
                  <h2>Tasks students miss most</h2>
                  {s.most_failed_tasks.length === 0 ? (
                    <p className="small muted">No task has been failed by anyone yet.</p>
                  ) : (
                    <table className="data">
                      <thead><tr><th>Task</th><th>Failed</th><th>Rate</th></tr></thead>
                      <tbody>
                        {s.most_failed_tasks.map((r) => (
                          <tr key={`${r.assignment_id}-${r.task_id}`}>
                            <td>{r.task_title}<div className="small muted">{r.assignment_title}</div></td>
                            <td>{r.failed}/{r.attempts}</td>
                            <td className="score">{pct(r.failure_rate)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </section>

                <section className="card" data-testid="most-missed-checks">
                  <h2>Checks students miss most</h2>
                  {s.most_missed_checks.length === 0 ? (
                    <p className="small muted">No check has been failed by anyone yet.</p>
                  ) : (
                    <table className="data">
                      <thead><tr><th>Check</th><th>Failed</th><th>Rate</th></tr></thead>
                      <tbody>
                        {s.most_missed_checks.map((r) => (
                          <tr key={`${r.assignment_id}-${r.task_id}-${r.check}`}>
                            <td className="mono small">{r.check}
                              <div className="small muted">{r.assignment_title} · {r.task_title}</div></td>
                            <td>{r.failed}/{r.attempts}</td>
                            <td className="score">{pct(r.failure_rate)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </section>
              </div>

              <p className="small muted" style={{ margin: 0 }}>
                Scores follow each assignment&apos;s grade policy over counted attempts; an interrupted lab is
                listed under <strong>Interrupted</strong> and never counted against a student.
              </p>
            </>
          )}
        </div>
      </main>
      <style>{`
        .stats { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }
        .stat-value { font-size: 30px; font-weight: 700; line-height: 1.1; margin: 4px 0 2px; }
      `}</style>
    </Shell>
  );
}
