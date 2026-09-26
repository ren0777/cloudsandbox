"use client";
// Lab Builder editor (phase 8): Overview, Tasks (check forms generated from the grader's parameter schemas),
// Scripts, YAML, student Preview and Test & publish, with an always-visible validation panel.
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { OverviewTab } from "@/components/lab-builder/overview";
import { PreviewTab } from "@/components/lab-builder/preview";
import { ScriptsTab } from "@/components/lab-builder/scripts";
import { TasksTab } from "@/components/lab-builder/tasks";
import { TestPublishTab } from "@/components/lab-builder/test-publish";
import { ValidationPanel } from "@/components/lab-builder/validation";
import { YamlTab } from "@/components/lab-builder/yaml";
import { Shell } from "@/components/shell";
import { ErrorBanner } from "@/components/ui";
import { api } from "@/lib/api";
import { type Catalogue, type Content, type Draft, type ErrorRow, type Lab, STATUS_LABEL, STATUS_PILL,
  type Validation } from "@/lib/builder";

const TABS = [
  { id: "overview", label: "Overview" }, { id: "tasks", label: "Tasks" }, { id: "scripts", label: "Scripts" },
  { id: "yaml", label: "YAML" }, { id: "preview", label: "Preview" }, { id: "test", label: "Test & publish" },
] as const;
type Tab = (typeof TABS)[number]["id"];
const SAVE_FIRST: Tab[] = ["yaml", "preview", "test"];  // these show the saved draft

export default function DraftEditor() {
  const { id } = useParams<{ id: string }>();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [content, setContent] = useState<Content | null>(null);
  const [dirty, setDirty] = useState(false);
  const [rev, setRev] = useState(0);  // bumps when content is replaced from the server (remounts form state)
  const [catalogue, setCatalogue] = useState<Catalogue | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [focusTask, setFocusTask] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const contentRef = useRef<Content | null>(null);
  contentRef.current = content;

  const replace = useCallback((d: Draft) => {
    setDraft(d); setContent(d.content); setDirty(false); setRev((r) => r + 1);
  }, []);

  const load = useCallback(async () => {
    try { replace(await api<Draft>(`/api/instructor/builder/drafts/${id}`)); } catch (e) { setError(e); }
  }, [id, replace]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { void api<Catalogue>("/api/instructor/builder/check-types").then(setCatalogue).catch(setError); }, []);

  // While a test runs, poll the draft (content is locked, so only status and results change).
  const testing = draft?.status === "testing";
  useEffect(() => {
    if (!testing) return;
    const t = setInterval(() => {
      void api<Draft>(`/api/instructor/builder/drafts/${id}`).then((d) => setDraft(d)).catch(() => undefined);
    }, 2500);
    return () => clearInterval(t);
  }, [testing, id]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const save = useCallback(async (): Promise<Draft | null> => {
    const c = contentRef.current;
    if (!draft || !c) return null;
    setSaving(true); setError(null);
    try {
      const files: Record<string, string> = {};
      for (const n of draft.editable_files) files[n] = c.files[n] ?? "";
      const d = await api<Draft>(`/api/instructor/builder/drafts/${draft.id}`, { method: "PUT", body: { lab: c.lab, files } });
      setDraft(d);
      if (contentRef.current === c) setDirty(false);  // nothing typed while saving
      return d;
    } catch (e) { setError(e); return null; } finally { setSaving(false); }
  }, [draft]);

  const edit = (fn: (c: Content) => Content) => {
    setContent((c) => (c ? fn(c) : c));
    setDirty(true);
  };
  const setLab = (lab: Lab) => edit((c) => ({ ...c, lab }));
  const setFile = (name: string, text: string) => edit((c) => ({ ...c, files: { ...c.files, [name]: text } }));

  async function go(next: Tab) {
    if (SAVE_FIRST.includes(next) && dirty && !(await save())) return;
    setTab(next);
  }

  async function revalidate() {
    if (!draft) return;
    setValidating(true);
    try {
      if (dirty) await save();
      else {
        const v = await api<Validation>(`/api/instructor/builder/drafts/${draft.id}/validate`, { method: "POST" });
        setDraft({ ...draft, validation: v });
      }
    } catch (e) { setError(e); } finally { setValidating(false); }
  }

  function jump(row: ErrorRow) {
    if (row.task) { setFocusTask(row.task); void go("tasks"); setTimeout(() => document.getElementById(`task-${row.task}`)?.scrollIntoView({ block: "start", behavior: "smooth" }), 50); }
    else if (row.loc?.startsWith("private/") || row.loc?.startsWith("public/") || row.message.startsWith("private/")) void go("scripts");
    else void go("overview");
  }

  async function runTest() {
    if (!draft) return;
    const saved = dirty ? await save() : draft;
    if (!saved) return;
    setDraft(await api<Draft>(`/api/instructor/builder/drafts/${draft.id}/test`, { method: "POST" }));
  }

  if (!draft || !content) {
    return <Shell><ErrorBanner error={error} onRetry={() => void load()} />{!error && <p className="muted"><span className="spinner" /> Loading…</p>}</Shell>;
  }
  const readOnly = draft.status === "testing" || draft.status === "published";
  const lab = content.lab;

  return (
    <Shell>
      <div className="stack" style={{ gap: 16 }}>
        <div className="row between" style={{ alignItems: "flex-end" }}>
          <div>
            <Link href="/instructor/labs" className="small">← Labs</Link>
            <div className="eyebrow" style={{ marginTop: 10 }}>Lab draft · <span className="mono">{lab.id}@{lab.version}</span></div>
            <h1 data-testid="draft-title">{lab.title || "Untitled lab"}</h1>
          </div>
          <div className="row">
            <span className={`pill ${STATUS_PILL[draft.status]}`} data-testid="draft-status">{STATUS_LABEL[draft.status]}</span>
            {dirty && <span className="small" style={{ color: "var(--warn)" }}>Unsaved changes</span>}
            <button className="primary" onClick={() => void save()} disabled={!dirty || saving || readOnly} data-testid="save-draft">
              {saving ? <><span className="spinner" /> Saving…</> : "Save"}</button>
          </div>
        </div>
        {draft.status === "published" && <div className="banner info small"><div>This draft is published and read-only. Use <strong>Prepare next version</strong> on the Test &amp; publish tab to change the lab.</div></div>}
        {draft.status === "testing" && <div className="banner info small"><span className="spinner" /><div>A test run is in progress; editing is locked until it finishes.</div></div>}
        <ErrorBanner error={error} />

        <div className="lb-layout">
          <div className="stack" style={{ minWidth: 0 }}>
            <div className="lb-tabs" role="tablist" aria-label="Lab editor">
              {TABS.map((t) => (
                <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? "on" : ""}
                  onClick={() => void go(t.id)} data-testid={`tab-${t.id}`}>{t.label}</button>
              ))}
            </div>
            <div className="card" role="tabpanel">
              {(tab === "overview" || tab === "tasks" || tab === "scripts") && (
                <fieldset disabled={readOnly} className="lb-plain" key={rev}>
                  {tab === "overview" && <OverviewTab lab={lab} catalogue={catalogue} validation={draft.validation} onChange={setLab} />}
                  {tab === "tasks" && <TasksTab lab={lab} catalogue={catalogue} validation={draft.validation} focusTask={focusTask} onChange={setLab} />}
                  {tab === "scripts" && <ScriptsTab content={content} readOnlyFiles={draft.read_only_files} validation={draft.validation} onFile={setFile} />}
                </fieldset>
              )}
              {tab === "yaml" && <YamlTab draftId={draft.id} rev={rev} readOnly={readOnly} onApplied={replace} />}
              {tab === "preview" && <PreviewTab draftId={draft.id} version={draft.updated_at} />}
              {tab === "test" && <TestPublishTab draft={draft} dirty={dirty} onRun={runTest} onPublished={(d) => setDraft(d)} />}
            </div>
          </div>
          <aside>
            <ValidationPanel v={draft.validation} dirty={dirty} busy={validating || saving} onRevalidate={() => void revalidate()} onJump={jump} />
          </aside>
        </div>
      </div>
      <style>{`
        .lb-layout { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 16px; align-items: start; }
        .lb-layout aside { position: sticky; top: 68px; }
        @media (max-width: 980px) { .lb-layout { grid-template-columns: 1fr; } .lb-layout aside { position: static; } }
        .lb-tabs { display: flex; gap: 4px; flex-wrap: wrap; }
        .lb-tabs button { border-radius: 8px; }
        .lb-tabs button.on { background: var(--ink); color: #fff; border-color: var(--ink); }
        .lb-plain { border: 0; padding: 0; margin: 0; min-width: 0; }
        .lb-grid { display: grid; gap: 12px 14px; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); }
        .lb-wide { grid-column: 1 / -1; }
        .lb-hint { font-weight: 400; color: var(--muted); font-size: 12px; }
        .lb-sub { font-size: 12px; font-weight: 650; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); margin-bottom: 6px; }
        .lb-fieldset { border: 1px solid var(--line); border-radius: var(--radius); padding: 10px 14px 12px; margin: 0; }
        .lb-fieldset legend { font-size: 13px; font-weight: 600; color: var(--ink-2); padding: 0 4px; }
        .lb-inline { flex-direction: row !important; align-items: center; gap: 6px !important; font-weight: 500; }
        .lb-inline input { width: auto; }
        .lb-task.lb-focus { border-color: var(--signal); box-shadow: 0 0 0 3px var(--signal-soft); }
        .lb-check { border: 1px dashed var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; }
        .lb-code { font-size: 13px; line-height: 1.45; background: #fbfcfe; }
        pre.lb-code { white-space: pre-wrap; border: 1px solid var(--line); border-radius: 8px; padding: 10px; margin: 6px 0 0; }
        .lb-errs { margin: 6px 0 0; padding-left: 18px; color: var(--fail); font-size: 12px; font-weight: 400; }
        .lb-validation h3 { font-size: 15px; }
        .lb-val-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; max-height: 60vh; overflow: auto; }
        .lb-val-row { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; width: 100%; text-align: left;
          font-weight: 400; font-size: 13px; line-height: 1.35; padding: 8px; border-radius: 6px; }
        .lb-val-row:hover { background: var(--fail-soft) !important; }
        .lb-val-where { font-size: 11px; color: var(--fail); }
        .lb-preview-tasks { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 10px; }
        .lb-checks th, .lb-checks td { padding: 6px 8px; }
        .lb-ro summary { cursor: pointer; }
      `}</style>
    </Shell>
  );
}
