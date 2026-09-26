"use client";
// Student XP, level and badges. Everything shown here is computed by the API from graded attempts.
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";

export type BadgeView = { id: string; title: string; description: string; icon: string; xp: number; earned?: boolean; awarded_at?: string | null };
type Progress = { xp: number; lab_xp: number; badge_xp: number; level: number; title: string; xp_for_level: number;
  xp_for_next: number | null; badges: BadgeView[] };

export function ProgressCard({ leaderboards }: { leaderboards: { id: string; code: string }[] }) {
  const [p, setP] = useState<Progress | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => { void api<Progress>("/api/me/progress").then(setP).catch(() => undefined); }, []);
  if (!p) return null;
  const earned = p.badges.filter((b) => b.earned);
  const span = p.xp_for_next === null ? 1 : p.xp_for_next - p.xp_for_level;
  const pct = p.xp_for_next === null ? 100 : Math.min(100, Math.round(((p.xp - p.xp_for_level) / span) * 100));
  return (
    <section className="card progress-card" data-testid="progress-card">
      <div className="pc-level">
        <div className="pc-badge" aria-hidden>{p.level}</div>
        <div className="grow">
          <div className="eyebrow">Level {p.level}</div>
          <div className="pc-title">{p.title}</div>
          <div className="pc-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}
            aria-label={p.xp_for_next === null ? "Top level reached" : `${p.xp_for_next - p.xp} XP to the next level`}><span style={{ width: `${pct}%` }} /></div>
          <div className="small muted"><strong className="score" style={{ color: "var(--ink)" }} data-testid="xp-total">{p.xp} XP</strong>
            {p.xp_for_next !== null ? ` · ${p.xp_for_next - p.xp} to level ${p.level + 1}` : " · top level"}
            <span title="Your best counted score in each lab, plus badge bonuses"> · {p.lab_xp} from labs, {p.badge_xp} from badges</span></div>
        </div>
      </div>
      <div className="pc-badges">
        <div className="row between"><span className="eyebrow">Badges · {earned.length} of {p.badges.length}</span>
          <button className="small ghost" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? "Hide all" : "See all"}</button></div>
        <div className="pc-medals">
          {(open ? p.badges : earned).map((b) => (
            <div key={b.id} className={`medal ${b.earned ? "on" : "off"}`} title={`${b.title}: ${b.description}`} data-testid={b.earned ? "badge-earned" : "badge-locked"}>
              <span className="medal-icon" aria-hidden>{b.icon}</span>
              <span className="medal-text"><strong>{b.title}</strong><span>{b.earned ? `Earned ${fmtDate(b.awarded_at)}` : `${b.description} +${b.xp} XP`}</span></span>
            </div>))}
          {!open && earned.length === 0 && <p className="small muted" style={{ margin: 0 }}>Complete a lab to earn your first badge.</p>}
        </div>
        {leaderboards.length > 0 && <div className="row small">{leaderboards.map((c) => (
          <Link key={c.id} href={`/courses/${c.id}/leaderboard`} data-testid="leaderboard-link">{c.code} leaderboard →</Link>))}</div>}
      </div>
      <style>{`
        .progress-card { display: grid; grid-template-columns: minmax(240px, 1fr) minmax(0, 2fr); gap: 22px; }
        .pc-level { display: flex; gap: 14px; align-items: center; }
        .pc-badge { width: 54px; height: 54px; border-radius: 14px; display: grid; place-items: center; flex: none;
          font: 700 24px var(--font-display); color: #fff; background: linear-gradient(145deg, var(--ink-2), var(--ink)); box-shadow: inset 0 0 0 3px #5fd3f0; }
        .pc-title { font: 650 18px var(--font-display); margin: 2px 0 8px; }
        .pc-bar { height: 8px; border-radius: 4px; background: #e7ecf4; overflow: hidden; margin-bottom: 6px; }
        .pc-bar span { display: block; height: 100%; background: var(--signal); }
        .pc-medals { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
        .medal { display: flex; gap: 8px; align-items: center; border: 1px solid var(--line); border-radius: 10px; padding: 6px 10px; max-width: 280px; }
        .medal.on { background: var(--signal-soft); border-color: #b9e3f1; }
        .medal.off { opacity: .6; border-style: dashed; }
        .medal-icon { font-size: 20px; width: 26px; text-align: center; }
        .medal.off .medal-icon { filter: grayscale(1); }
        .medal-text { display: flex; flex-direction: column; font-size: 12px; line-height: 1.3; }
        .medal-text span { color: var(--muted); }
        @media (max-width: 800px) { .progress-card { grid-template-columns: 1fr; } }
      `}</style>
    </section>
  );
}

export function BadgesEarned({ badges }: { badges: BadgeView[] }) {
  if (badges.length === 0) return null;
  return (
    <div className="banner pass" role="status" data-testid="badges-earned" style={{ display: "block" }}>
      <strong>New badge{badges.length > 1 ? "s" : ""}!</strong>
      <div className="row" style={{ marginTop: 6 }}>{badges.map((b) => (
        <span key={b.id} className="pill pass" title={b.description}><span aria-hidden>{b.icon}</span> {b.title} · +{b.xp} XP</span>))}</div>
    </div>
  );
}
