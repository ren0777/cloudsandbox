"use client";
import { useEffect, useState } from "react";
import { ErrorBanner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { Draft, ErrorRow } from "@/lib/builder";
import { ErrorList } from "./validation";

/** "Edit as YAML": the lab.yaml of the saved draft. Applying it replaces the lab exactly like a form save
 * (YAML comments are not kept: the draft stores the lab as JSON). */
export function YamlTab({ draftId, rev, readOnly, onApplied }: {
  draftId: string; rev: number; readOnly: boolean; onApplied: (d: Draft) => void;
}) {
  const [text, setText] = useState<string | null>(null);
  const [saved, setSaved] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    api<{ yaml: string }>(`/api/instructor/builder/drafts/${draftId}/yaml`)
      .then((r) => { if (live) { setText(r.yaml); setSaved(r.yaml); } }).catch(setError);
    return () => { live = false; };
  }, [draftId, rev]);

  async function apply() {
    setBusy(true); setError(null);
    try {
      const d = await api<Draft & { yaml: string }>(`/api/instructor/builder/drafts/${draftId}/yaml`, { method: "PUT", body: { yaml: text } });
      setText(d.yaml); setSaved(d.yaml);
      onApplied(d);
    } catch (e) { setError(e); } finally { setBusy(false); }
  }

  const rows = error instanceof ApiError ? (error.extra.errors as ErrorRow[] | undefined) ?? [] : [];
  if (text === null) return error ? <ErrorBanner error={error} /> : <p className="muted"><span className="spinner" /> Loading…</p>;
  return (
    <div className="stack">
      <p className="small muted" style={{ margin: 0 }}>The same lab as the form, as <code>lab.yaml</code>. Changes here replace the form&apos;s content when applied; comments are not kept.</p>
      <textarea className="mono lb-code" rows={28} spellCheck={false} value={text} readOnly={readOnly} data-testid="yaml-text"
        onChange={(e) => setText(e.target.value)} aria-label="lab.yaml" />
      <ErrorBanner error={error} />
      <ErrorList rows={rows} />
      <div className="row">
        <button className="primary" onClick={() => void apply()} disabled={readOnly || busy || text === saved} data-testid="yaml-apply">
          {busy ? <><span className="spinner" /> Applying…</> : "Apply YAML"}</button>
        <button onClick={() => { setText(saved); setError(null); }} disabled={text === saved}>Discard changes</button>
      </div>
    </div>
  );
}
