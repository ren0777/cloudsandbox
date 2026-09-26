"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Shell } from "@/components/shell";
import { ErrorBanner } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";

type Cell = { status: "not_open" | "not_started" | "in_progress" | "submitted" | "interrupted" | "missed";
  score: string | null; max_score: string; percentage: string | null; attempts_used: number; attempts_allowed: number;
  late: boolean | null; submitted_at: string | null; attempt_id: string | null;
  attempts: { id: string; attempt_no: number; score: string; counts: boolean; late: boolean; regraded: boolean }[] };
type Book = { course: { id: string; code: string; title: string };
  assignments: { id: string; title: string; lab: string | null; max_score: string | null; due_at: string; close_at: string; grade_policy: string }[];
  students: { user: { id: string; name: string; email: string; short_id: string }; cells: Record<string, Cell>; total: string; possible: string; percentage: string | null }[] };

const STATUS_TEXT: Record<Cell["status"], string> = { not_open: "Not open", not_started: "Not started", in_progress: "Working now",
  submitted: "Submitted", interrupted: "Interrupted", missed: "Missed" };
const band = (p: string | null) => p === null ? "" : Number(p) >= 80 ? "hi" : Number(p) >= 50 ? "mid" : "lo";

export default function Gradebook() {
  const { id } = useParams<{ id: string }>();
  const [book, setBook] = useState<Book | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [q, setQ] = useState("");
  const load = useCallback(() => api<Book>(`/api/instructor/courses/${id}/gradebook`).then(setBook).catch(setError), [id]);
  useEffect(() => { void load(); }, [load]);
  const rows = useMemo(() => (book?.students ?? []).filter((s) =>
    `${s.user.name} ${s.user.email} ${s.user.short_id}`.toLowerCase().includes(q.toLowerCase())), [book, q]);

  if (!book) return <Shell><ErrorBanner error={error} onRetry={load} />{!error && <p className="muted">Loading…</p>}</Shell>;
  const submittedCount = (aid: string) => book.students.filter((s) => s.cells[aid]?.status === "submitted").length;
  return (
    <Shell wide>
      <main className="page" style={{ maxWidth: 1400 }}>
        <div className="stack" style={{ gap: 18 }}>
          <Link href={`/instructor/courses/${id}`} className="small">← {book.course.code}</Link>
          <div className="row between">
            <div><div className="eyebrow">Gradebook · {book.students.length} students · {book.assignments.length} labs</div><h1>{book.course.code} · {book.course.title}</h1></div>
            <div className="row">
              <input placeholder="Filter students" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 220 }} aria-label="Filter students" />
              <button className="small" onClick={() => void load()}>Refresh</button>
              <a className="btn small primary" href={`/api/instructor/courses/${id}/gradebook.csv`} data-testid="export-gradebook">Export CSV</a>
            </div>
          </div>
          <ErrorBanner error={error} />
          {book.assignments.length === 0 ? <div className="card flat muted">No labs assigned yet.</div> : (
            <div className="card gb-wrap" style={{ padding: 0 }}>
              <table className="gb">
                <thead>
                  <tr>
                    <th className="who">Student</th>
                    {book.assignments.map((a) => (
                      <th key={a.id} scope="col">
                        <Link href={`/instructor/assignments/${a.id}`} className="gb-title">{a.title}</Link>
                        <div className="gb-meta">due {fmtDate(a.due_at)} · {a.grade_policy} · {submittedCount(a.id)}/{book.students.length} submitted</div>
                      </th>))}
                    <th className="total">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.length === 0 && <tr><td className="who muted" colSpan={book.assignments.length + 2}>No students match.</td></tr>}
                  {rows.map((s) => (
                    <tr key={s.user.id} data-testid="gradebook-row">
                      <th scope="row" className="who"><div className="nm">{s.user.name}</div><div className="gb-meta">{s.user.email} · <span className="mono">{s.user.short_id}</span></div></th>
                      {book.assignments.map((a) => <GradeCell key={a.id} cell={s.cells[a.id]} />)}
                      <td className="total"><div className="score">{Number(s.total)}<span className="gb-meta"> / {Number(s.possible)}</span></div>
                        <div className="gb-meta">{s.percentage ?? "—"}%</div></td>
                    </tr>))}
                </tbody>
              </table>
            </div>)}
          <p className="small muted" style={{ margin: 0 }}>Each cell is the score that counts under the lab&apos;s policy (best or latest counted attempt, after regrades).
            Select a score to see that attempt&apos;s per-check evidence. <span className="late-tag">late</span> marks a late submission, * a regrade.</p>
        </div>
      </main>
      <style>{`
        .gb-wrap { overflow: auto; max-height: calc(100vh - 230px); }
        .gb { border-collapse: separate; border-spacing: 0; font-size: 14px; min-width: 100%; }
        .gb th, .gb td { border-bottom: 1px solid var(--line); border-right: 1px solid var(--line); padding: 8px 10px; text-align: left; vertical-align: top; }
        .gb thead th { position: sticky; top: 0; background: #f7f9fc; z-index: 2; min-width: 150px; font-weight: 600; }
        .gb .who { position: sticky; left: 0; background: #fff; z-index: 1; min-width: 220px; }
        .gb thead .who { z-index: 3; background: #f7f9fc; }
        .gb .nm { font-weight: 600; }
        .gb-title { font-weight: 650; color: var(--ink); }
        .gb-meta { font-size: 12px; color: var(--muted); font-weight: 400; }
        .gb .total { min-width: 110px; background: #fafbfd; }
        .gb-cell { display: block; border-radius: 8px; padding: 6px 8px; color: inherit; }
        a.gb-cell:hover { text-decoration: none; outline: 2px solid var(--signal-soft); }
        .gb-cell.hi { background: var(--pass-soft); } .gb-cell.mid { background: var(--warn-soft); } .gb-cell.lo { background: var(--fail-soft); }
        .gb-cell .score { font-size: 16px; }
        .gb-status { font-size: 12px; color: var(--muted); }
        .gb-status.missed, .gb-status.interrupted { color: var(--fail); }
        .gb-status.in_progress { color: var(--signal-strong); font-weight: 600; }
        .late-tag { font: 600 10px/1 var(--font-mono); text-transform: uppercase; letter-spacing: .06em; background: var(--warn-soft); color: var(--warn); padding: 2px 5px; border-radius: 4px; }
      `}</style>
    </Shell>
  );
}

function GradeCell({ cell }: { cell: Cell | undefined }) {
  if (!cell) return <td />;
  const regraded = cell.attempts.some((a) => a.id === cell.attempt_id && a.regraded);
  if (cell.status === "submitted" && cell.attempt_id) {
    return (
      <td data-testid="gradebook-cell">
        <Link href={`/instructor/attempts/${cell.attempt_id}`} className={`gb-cell ${band(cell.percentage)}`}
          title={`Submitted ${fmtDate(cell.submitted_at)} · attempt ${cell.attempts.find((a) => a.id === cell.attempt_id)?.attempt_no}`}>
          <span className="score">{Number(cell.score)}{regraded ? "*" : ""}</span><span className="gb-meta"> / {Number(cell.max_score)} · {cell.percentage}%</span>
          <div className="gb-meta">{cell.attempts_used}/{cell.attempts_allowed} attempts {cell.late && <span className="late-tag">late</span>}</div>
        </Link>
      </td>);
  }
  return (
    <td data-testid="gradebook-cell">
      <div className="gb-cell"><span className={`gb-status ${cell.status}`}>{STATUS_TEXT[cell.status]}</span>
        <div className="gb-meta">{cell.attempts_used}/{cell.attempts_allowed} attempts</div></div>
    </td>);
}
