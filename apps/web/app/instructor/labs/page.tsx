"use client";
// Lab library (phase 8): my drafts, my published labs, labs shared by other instructors and the built-in
// missions, with New, Clone and Import. Export links download the full pack (it contains the solution).
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/components/auth";
import { Shell } from "@/components/shell";
import { ErrorBanner } from "@/components/ui";
import { api } from "@/lib/api";
import { type Draft, type DraftSummary, type LabVersionRow, STATUS_LABEL, STATUS_PILL } from "@/lib/builder";
import { fmtDate } from "@/lib/format";

type LabGroup = { lab_id: string; slug: string; title: string; shared: boolean; builtin: boolean; mine: boolean;
  owner: string | null; versions: LabVersionRow[] };

function groupByLab(rows: LabVersionRow[]): LabGroup[] {
  const m = new Map<string, LabGroup>();
  for (const v of rows) {
    const g = m.get(v.lab_id) ?? { lab_id: v.lab_id, slug: v.lab, title: v.title, shared: v.shared, builtin: v.builtin,
      mine: v.mine, owner: v.owner?.name ?? null, versions: [] };
    g.versions.push(v);
    m.set(v.lab_id, g);
  }
  return [...m.values()].sort((a, b) => a.title.localeCompare(b.title));
}

export default function LabLibrary() {
  const { me } = useAuth();
  const router = useRouter();
  const [drafts, setDrafts] = useState<DraftSummary[] | null>(null);
  const [labs, setLabs] = useState<LabGroup[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const [d, v] = await Promise.all([
        api<{ drafts: DraftSummary[] }>("/api/instructor/builder/drafts"),
        api<{ lab_versions: LabVersionRow[] }>("/api/instructor/lab-versions"),
      ]);
      setDrafts(d.drafts);
      setLabs(groupByLab(v.lab_versions));
    } catch (e) { setError(e); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function clone(versionId: string) {
    setBusy(versionId); setError(null);
    try {
      const d = await api<Draft>("/api/instructor/builder/drafts", { method: "POST", body: { source: "clone", lab_version_id: versionId } });
      router.push(`/instructor/labs/drafts/${d.id}`);
    } catch (e) { setError(e); setBusy(null); }
  }

  async function importPack(file: File) {
    setBusy("import"); setError(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const d = await api<Draft>("/api/instructor/builder/drafts/import", { method: "POST", form });
      router.push(`/instructor/labs/drafts/${d.id}`);
    } catch (e) { setError(e); setBusy(null); }
    if (fileRef.current) fileRef.current.value = "";
  }

  async function remove(d: DraftSummary) {
    if (!window.confirm(`Delete the draft “${d.title}”? Published versions are not affected.`)) return;
    try { await api(`/api/instructor/builder/drafts/${d.id}`, { method: "DELETE" }); await load(); } catch (e) { setError(e); }
  }

  async function share(g: LabGroup, shared: boolean) {
    try { await api(`/api/instructor/labs/${g.lab_id}/share`, { method: "POST", body: { shared } }); await load(); } catch (e) { setError(e); }
  }

  const mine = labs?.filter((g) => g.mine) ?? [];
  const others = labs?.filter((g) => !g.mine && !g.builtin) ?? [];
  const builtin = labs?.filter((g) => g.builtin) ?? [];
  const admin = me?.role === "admin";

  return (
    <Shell>
      <div className="stack" style={{ gap: 20 }}>
        <div className="row between">
          <div><div className="eyebrow">Lab Builder</div><h1>Labs</h1>
            <p className="lede" style={{ margin: "6px 0 0" }}>Write your own labs, test them in real sandboxes and publish them for your courses.</p></div>
          <div className="row">
            <input ref={fileRef} type="file" accept=".tar.gz,.tgz,.tar,application/gzip" hidden data-testid="import-file"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) void importPack(f); }} />
            <button onClick={() => fileRef.current?.click()} disabled={busy === "import"} data-testid="import-lab">
              {busy === "import" ? <><span className="spinner" /> Importing…</> : "Import pack"}</button>
            <button className="primary" onClick={() => setCreating(true)} data-testid="new-lab">New lab</button>
          </div>
        </div>
        <ErrorBanner error={error} />

        <section className="card" aria-labelledby="drafts-h">
          <h2 id="drafts-h">{admin ? "Drafts" : "My drafts"}</h2>
          <table className="data" style={{ marginTop: 10 }}>
            <thead><tr><th>Lab</th><th>Status</th><th>Checks</th>{admin && <th>Author</th>}<th>Updated</th><th /></tr></thead>
            <tbody>
              {drafts?.length === 0 && <tr><td colSpan={admin ? 6 : 5} className="muted">No drafts yet. Start a <strong>New lab</strong>, or <strong>Clone</strong> one below.</td></tr>}
              {drafts?.map((d) => (
                <tr key={d.id} data-testid="draft-row">
                  <td><Link href={`/instructor/labs/drafts/${d.id}`} data-testid="draft-link">{d.title}</Link>
                    <div className="small muted mono">{d.slug}</div></td>
                  <td><span className={`pill ${STATUS_PILL[d.status]}`}>{STATUS_LABEL[d.status]}</span></td>
                  <td>{d.validation?.ok ? <span className="pill pass">Valid</span>
                    : <span className="pill warn">{d.validation?.errors.length ?? 0} to fix</span>}</td>
                  {admin && <td>{d.owner.name}</td>}
                  <td className="small">{fmtDate(d.updated_at)}</td>
                  <td style={{ textAlign: "right" }}>
                    {d.status !== "testing" && <button className="small ghost danger" onClick={() => void remove(d)}>Delete</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <LabSection title={admin ? "Authored labs (mine)" : "My labs"} empty="You haven't published a lab yet." groups={mine}
          busy={busy} onClone={clone} onShare={share} testId="my-labs" />
        <LabSection title={admin ? "Other authors' labs" : "Shared by other instructors"} empty="No shared labs yet." groups={others}
          busy={busy} onClone={clone} testId="shared-labs" />
        <LabSection title="Built-in missions" empty="No built-in missions are installed." groups={builtin}
          busy={busy} onClone={clone} testId="builtin-labs" />
      </div>
      {creating && <NewLab onClose={() => setCreating(false)} onCreated={(id) => router.push(`/instructor/labs/drafts/${id}`)} />}
    </Shell>
  );
}

function LabSection({ title, empty, groups, busy, onClone, onShare, testId }: {
  title: string; empty: string; groups: LabGroup[]; busy: string | null; testId: string;
  onClone: (versionId: string) => void; onShare?: (g: LabGroup, shared: boolean) => void;
}) {
  return (
    <section className="card" data-testid={testId}>
      <h2>{title}</h2>
      <table className="data" style={{ marginTop: 10 }}>
        <thead><tr><th>Lab</th><th>Latest version</th><th>Visibility</th><th /></tr></thead>
        <tbody>
          {groups.length === 0 && <tr><td colSpan={4} className="muted">{empty}</td></tr>}
          {groups.map((g) => {
            const latest = g.versions[g.versions.length - 1];
            return (
              <tr key={g.lab_id} data-testid="lab-row">
                <td><strong>{g.title}</strong><div className="small muted mono">{g.slug}</div>
                  {g.owner && !g.mine && <div className="small muted">by {g.owner}</div>}</td>
                <td className="mono">v{latest.version}{g.versions.length > 1 && <span className="muted small"> · {g.versions.length} versions</span>}</td>
                <td>{g.builtin ? <span className="pill">Everyone</span>
                  : onShare ? (
                    <label className="row small" style={{ flexDirection: "row", gap: 6, fontWeight: 400 }}>
                      <input type="checkbox" checked={g.shared} style={{ width: "auto" }} data-testid="share-toggle"
                        onChange={(e) => onShare(g, e.target.checked)} />
                      Shared with all instructors
                    </label>
                  ) : <span className={`pill ${g.shared ? "info" : ""}`}>{g.shared ? "Shared" : "Private"}</span>}</td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  <a className="btn small ghost" href={`/api/instructor/lab-versions/${latest.id}/export`} download
                    title="Download the full pack (includes the reference solution)">Export</a>{" "}
                  <button className="small" onClick={() => onClone(latest.id)} disabled={busy === latest.id} data-testid="clone-lab">
                    {busy === latest.id ? <><span className="spinner" /> Cloning…</> : g.mine ? "New version" : "Clone"}</button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

function NewLab({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const [title, setTitle] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function save(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try {
      const d = await api<Draft>("/api/instructor/builder/drafts", { method: "POST", body: { source: "blank", title } });
      onCreated(d.id);
    } catch (err) { setError(err); setBusy(false); }
  }
  return (
    <div className="dialog-backdrop" role="dialog" aria-modal aria-labelledby="newlab-title" onClick={onClose}>
      <form className="dialog stack" onClick={(e) => e.stopPropagation()} onSubmit={save}>
        <h2 id="newlab-title">New lab</h2>
        <label>Title<input required autoFocus maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g. Host a static website on S3" data-testid="new-lab-title" /></label>
        <p className="small muted" style={{ margin: 0 }}>The draft starts as a one-task S3 lab with a reference solution. Nothing is visible to students until you test and publish it.</p>
        <ErrorBanner error={error} />
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" onClick={onClose}>Cancel</button>
          <button className="primary" disabled={busy || !title.trim()} data-testid="new-lab-create">Create draft</button>
        </div>
      </form>
    </div>
  );
}
