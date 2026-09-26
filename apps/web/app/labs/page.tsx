"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { ProgressCard } from "@/components/progress-card";
import { Shell } from "@/components/shell";
import { ErrorBanner, ScoreRing } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { AssignmentCard } from "@/lib/types";

export default function LabsPage() {
  const [items, setItems] = useState<AssignmentCard[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = () => api<{ assignments: AssignmentCard[] }>("/api/me/assignments")
    .then((r) => { setItems(r.assignments); setError(null); }).catch(setError);
  useEffect(() => { void load(); }, []);

  return (
    <Shell>
      <div className="stack" style={{ gap: 20 }}>
        <div>
          <div className="eyebrow">Your missions</div>
          <h1>My labs</h1>
        </div>
        <ErrorBanner error={error} onRetry={load} />
        {items && <ProgressCard leaderboards={Array.from(new Map(items.filter((a) => a.course && a.course.leaderboard && a.course.leaderboard !== "off")
          .map((a) => [a.course!.id, { id: a.course!.id, code: a.course!.code }])).values())} />}
        {items && items.length === 0 && (
          <div className="card flat muted">No labs are assigned to you yet. Your instructor will add them to your course.</div>
        )}
        <div className="grid">
          {items?.map((a) => (
            <Link key={a.id} href={`/labs/${a.id}`} className="card lab-card" data-testid="lab-card">
              <div className="lab-card-head">
                <div className="stack" style={{ gap: 6 }}>
                  <span className="eyebrow">{a.course?.code} · {a.services.map((s) => s.toUpperCase()).join(" · ")}</span>
                  {a.kind === "break_fix" && <span className="pill warn" style={{ alignSelf: "flex-start" }} data-testid="breakfix-tag">Break-fix: starts broken</span>}
                  <h2>{a.lab_title}</h2>
                </div>
                <ScoreRing score={a.final_score} max={a.max_score} size={58} />
              </div>
              <p className="muted small" style={{ margin: "8px 0 14px" }}>{a.summary}</p>
              <div className="row small">
                {a.active_session ? <span className="pill info">In progress</span>
                  : !a.is_open ? <span className="pill">Closed</span>
                  : a.attempts_left === 0 ? <span className="pill">No attempts left</span>
                  : a.is_late ? <span className="pill warn">Late window</span>
                  : <span className="pill pass">Open</span>}
                <span className="muted">Due {fmtDate(a.due_at)}</span>
                <span className="muted">· {a.attempts_used}/{a.attempts_allowed} attempts</span>
              </div>
            </Link>
          ))}
        </div>
      </div>
      <style>{`
        .lab-card-head { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; align-items: start; }
        .lab-card { color: inherit; display: block; transition: transform .12s, box-shadow .12s; }
        .lab-card:hover { text-decoration: none; transform: translateY(-2px); box-shadow: 0 8px 24px rgba(20,33,61,.1); }
      `}</style>
    </Shell>
  );
}
