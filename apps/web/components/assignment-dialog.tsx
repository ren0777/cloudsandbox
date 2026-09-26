"use client";
// Create or edit a lab assignment (course staff). The lab version is fixed once a student has started.
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ErrorBanner } from "./ui";

type LabVersion = { id: string; lab: string; title: string; version: string };
export type AssignmentValues = { id: string; title: string; lab_version_id?: string; open_at: string; due_at: string; close_at: string;
  allow_late?: boolean; max_attempts: number; grade_policy: string };

// <input type="datetime-local"> works in local time without a zone.
const toLocal = (iso: string) => { const d = new Date(iso); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };
const fromLocal = (v: string) => new Date(v).toISOString();
const inDays = (n: number) => { const d = new Date(); d.setDate(d.getDate() + n); d.setHours(23, 59, 0, 0); return d.toISOString(); };

export function AssignmentDialog({ courseId, existing, onClose }: { courseId?: string; existing?: AssignmentValues; onClose: (changed: boolean) => void }) {
  const [versions, setVersions] = useState<LabVersion[]>([]);
  const [labVersion, setLabVersion] = useState(existing?.lab_version_id ?? "");
  const [title, setTitle] = useState(existing?.title ?? "");
  const [openAt, setOpenAt] = useState(toLocal(existing?.open_at ?? new Date().toISOString()));
  const [dueAt, setDueAt] = useState(toLocal(existing?.due_at ?? inDays(7)));
  const [closeAt, setCloseAt] = useState(toLocal(existing?.close_at ?? inDays(8)));
  const [allowLate, setAllowLate] = useState(existing?.allow_late ?? true);
  const [attempts, setAttempts] = useState(existing?.max_attempts ?? 3);
  const [policy, setPolicy] = useState(existing?.grade_policy ?? "best");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    void api<{ lab_versions: LabVersion[] }>("/api/instructor/lab-versions").then((r) => {
      setVersions(r.lab_versions);
      if (!existing) { setLabVersion((v) => v || r.lab_versions[0]?.id || ""); }
    }).catch(setError);
  }, [existing]);
  const orderOk = openAt < dueAt && dueAt <= closeAt;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    const body = { title, open_at: fromLocal(openAt), due_at: fromLocal(dueAt), close_at: fromLocal(closeAt), allow_late: allowLate,
      max_attempts: attempts, grade_policy: policy };
    try {
      if (existing) await api(`/api/instructor/assignments/${existing.id}`, { method: "PATCH", body: { ...body, lab_version_id: labVersion || undefined, reason: reason || null } });
      else await api("/api/instructor/assignments", { method: "POST", body: { ...body, course_id: courseId, lab_version_id: labVersion } });
      onClose(true);
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  return (
    <div className="dialog-backdrop" role="dialog" aria-modal aria-labelledby="asg-title" onClick={() => onClose(false)}>
      <form className="dialog stack" onClick={(e) => e.stopPropagation()} onSubmit={save} style={{ width: "min(560px, 100%)" }}>
        <h2 id="asg-title">{existing ? "Edit assignment" : "New assignment"}</h2>
        <label>Lab<select value={labVersion} onChange={(e) => setLabVersion(e.target.value)} required data-testid="asg-lab">
          {versions.map((v) => <option key={v.id} value={v.id}>{v.title} · v{v.version}</option>)}</select>
          {existing && <span className="small muted" style={{ fontWeight: 400 }}>The lab can change only until the first student starts it.</span>}</label>
        <label>Title<input required maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Week 3: Serverless checkout" data-testid="asg-title" /></label>
        <div className="row" style={{ alignItems: "flex-start" }}>
          <label className="grow">Opens<input type="datetime-local" required value={openAt} onChange={(e) => setOpenAt(e.target.value)} /></label>
          <label className="grow">Due<input type="datetime-local" required value={dueAt} onChange={(e) => setDueAt(e.target.value)} data-testid="asg-due" /></label>
          <label className="grow">Closes<input type="datetime-local" required value={closeAt} onChange={(e) => setCloseAt(e.target.value)} data-testid="asg-close" /></label>
        </div>
        {!orderOk && <span className="small" style={{ color: "var(--fail)" }}>The lab must open before it is due, and be due no later than it closes.</span>}
        <div className="row" style={{ alignItems: "flex-start" }}>
          <label className="grow">Attempts per student<input type="number" min={1} max={20} value={attempts} onChange={(e) => setAttempts(Number(e.target.value))} data-testid="asg-attempts" /></label>
          <label className="grow">Score that counts<select value={policy} onChange={(e) => setPolicy(e.target.value)}>
            <option value="best">Best attempt</option><option value="latest">Latest attempt</option></select></label>
        </div>
        <label style={{ flexDirection: "row", alignItems: "center", gap: 8 }}><input type="checkbox" checked={allowLate} onChange={(e) => setAllowLate(e.target.checked)} style={{ width: "auto" }} />
          Accept late submissions between the due and closing times (marked late)</label>
        {existing && <label>Reason for the change (optional, recorded in the audit log)<input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} /></label>}
        <ErrorBanner error={error} />
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" onClick={() => onClose(false)}>Cancel</button>
          <button className="primary" disabled={busy || !orderOk || !title.trim() || !labVersion} data-testid="asg-save">{existing ? "Save changes" : "Create assignment"}</button>
        </div>
      </form>
    </div>
  );
}
