"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/components/auth";
import { Shell } from "@/components/shell";
import { ErrorBanner } from "@/components/ui";
import { api } from "@/lib/api";

type Entry = { rank: number; name: string; xp: number; level: number; badges: number; you: boolean };
type Board = { mode: "off" | "anonymous" | "named"; course?: { id: string; code: string; title: string };
  entries: Entry[]; me: Entry | null; students?: number };

export default function Leaderboard() {
  const { id } = useParams<{ id: string }>();
  const { me } = useAuth();
  const [b, setB] = useState<Board | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => { void api<Board>(`/api/courses/${id}/leaderboard`).then(setB).catch(setError); }, [id]);
  const back = me?.role === "student" ? "/labs" : `/instructor/courses/${id}`;
  return (
    <Shell>
      <div className="stack" style={{ gap: 18, maxWidth: 720 }}>
        <Link href={back} className="small">← Back</Link>
        <ErrorBanner error={error} />
        {b?.mode === "off" && <div className="card flat muted">Your instructor hasn&apos;t turned on the leaderboard for this course.</div>}
        {b && b.mode !== "off" && (
          <>
            <div><div className="eyebrow">{b.course?.code} · {b.mode === "anonymous" ? "anonymous names" : "real names"}</div><h1>Leaderboard</h1>
              <p className="small muted" style={{ margin: "6px 0 0" }}>XP from this course&apos;s labs: your best counted score in each lab, plus badges earned in them.
                {b.mode === "anonymous" && " Everyone appears under a stable nickname. Only your instructor sees real names."}</p></div>
            <ol className="board card" style={{ padding: 0 }}>
              {b.entries.map((e) => (
                <li key={`${e.rank}-${e.name}`} className={e.you ? "you" : ""} data-testid="board-row">
                  <span className={`rank r${e.rank}`}>{e.rank}</span>
                  <span className="grow"><strong>{e.name}</strong>{e.you && <span className="pill info" style={{ marginLeft: 8 }}>You</span>}
                    <span className="small muted"> · level {e.level} · {e.badges} badge{e.badges === 1 ? "" : "s"}</span></span>
                  <span className="score">{e.xp} XP</span>
                </li>))}
            </ol>
            {b.me && !b.entries.some((e) => e.you) && <p className="small">You: rank <strong>{b.me.rank}</strong> of {b.students} with {b.me.xp} XP.</p>}
          </>)}
      </div>
      <style>{`
        .board { list-style: none; margin: 0; }
        .board li { display: flex; align-items: center; gap: 14px; padding: 12px 16px; border-bottom: 1px solid var(--line); }
        .board li:last-child { border-bottom: 0; }
        .board li.you { background: var(--signal-soft); }
        .rank { width: 32px; height: 32px; border-radius: 50%; display: grid; place-items: center; font: 700 14px var(--font-display); background: #edf1f8; }
        .rank.r1 { background: #f5d76e; } .rank.r2 { background: #d9dee8; } .rank.r3 { background: #e8b98a; }
      `}</style>
    </Shell>
  );
}
