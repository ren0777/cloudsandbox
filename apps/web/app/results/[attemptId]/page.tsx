"use client";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Shell } from "@/components/shell";
import { ArchitectureDiagram, CostMeter } from "@/components/architecture-diagram";
import { BadgesEarned } from "@/components/progress-card";
import { ErrorBanner, ScoreRing } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate, TRIGGER_LABEL } from "@/lib/format";
import type { AttemptResult } from "@/lib/types";

function Result() {
  const { attemptId } = useParams<{ attemptId: string }>();
  const auto = useSearchParams().get("auto");
  const [r, setR] = useState<AttemptResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => { void api<AttemptResult>(`/api/attempts/${attemptId}`).then(setR).catch(setError); }, [attemptId]);

  if (!r) return <Shell><ErrorBanner error={error} />{!error && <p className="muted">Loading your result…</p>}</Shell>;
  const { attempt, result } = r;
  const perfect = result.score === result.max_score;
  return (
    <Shell>
      <div className="stack" style={{ gap: 20, maxWidth: 820 }}>
        <Link href={`/labs/${attempt.assignment_id}`} className="small">← Back to the lab</Link>
        <div className="card result-head">
          <ScoreRing score={result.score} max={result.max_score} size={96} />
          <div className="stack" style={{ gap: 6 }}>
            <span className="eyebrow">Attempt #{attempt.attempt_no} · {fmtDate(attempt.created_at)}</span>
            <h1 data-testid="final-score">{result.score} / {Number(result.max_score)}</h1>
            <div className="row">
              <span className={`pill ${attempt.trigger === "submit" ? "info" : "warn"}`}>{TRIGGER_LABEL[attempt.trigger]}</span>
              {attempt.late && <span className="pill warn">Late</span>}
              {!attempt.counts && <span className="pill">Not counted: nothing changed in your sandbox</span>}
              {attempt.regraded && <span className="pill">Regraded by your instructor</span>}
            </div>
          </div>
        </div>
        {auto && attempt.trigger !== "submit" && (
          <div className="banner info">{attempt.trigger === "staff"
            ? "Your instructor ended this lab, and the work in your sandbox was graded."
            : "Your lab was submitted automatically, so the work in your sandbox was still graded."}
            {!attempt.counts && " Nothing had changed since the lab started, so this doesn't use an attempt."}</div>
        )}
        {perfect && <div className="banner pass">Every task passed. Mission complete.</div>}
        <BadgesEarned badges={r.badges ?? []} />
        <div className="stack">
          {result.tasks.map((t) => (
            <div key={t.task_id} className={`card task-result ${t.passed ? "ok" : "no"}`}>
              <div className="row between">
                <h3>{t.passed ? "✓" : "✗"} {t.title}</h3>
                <span className="score">{t.marks_awarded} / {Number(t.marks_possible)}</span>
              </div>
              <ul className="checks">
                {t.checks.map((c, i) => (
                  <li key={i} className={c.passed ? "ok" : "no"}>
                    <span aria-hidden>{c.passed ? "✓" : "✗"}</span> {c.message}
                    {c.hidden && <span className="pill" style={{ marginLeft: 8 }}>Hidden check</span>}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        {r.insights && (
          <section className="card stack" data-testid="result-architecture">
            <div><h2>What you built</h2><p className="small muted" style={{ margin: "4px 0 0" }}>Your resources at the moment this attempt was graded.</p></div>
            {r.insights.cost && <CostMeter cost={r.insights.cost} />}
            <ArchitectureDiagram graph={r.insights.graph} />
          </section>)}
      </div>
      <style>{`
        .result-head { display: flex; gap: 20px; align-items: center; }
        .task-result.ok { border-left: 4px solid var(--pass); } .task-result.no { border-left: 4px solid var(--fail); }
        .checks { list-style: none; padding: 0; margin: 10px 0 0; display: flex; flex-direction: column; gap: 6px; font-size: 14px; }
        .checks li.ok span:first-child { color: var(--pass); } .checks li.no span:first-child { color: var(--fail); }
      `}</style>
    </Shell>
  );
}

export default function ResultPage() {
  return <Suspense><Result /></Suspense>;
}
