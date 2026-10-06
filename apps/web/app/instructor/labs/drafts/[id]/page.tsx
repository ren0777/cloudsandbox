"use client";
// Lab Builder editor (phase 8, plus the phase 9 Starting state tab): Overview, Tasks (check forms generated
// from the grader's parameter schemas), Starting state (typed break actions), Scripts, YAML, student Preview
// and Test & publish, with an always-visible validation panel.
//
// Editing model (phase 10, milestone 46):
//  * every edit is autosaved after a short debounce, with a visible Saving… / Saved / Save failed state;
//  * each save carries the content revision it was based on, so a stale autosave gets 409 instead of
//    overwriting content saved by another tab or by a test run;
//  * undo/redo walks a bounded history of content snapshots (keystrokes within a second coalesce), and
//    restores the form by remounting it so no tab keeps local state from the discarded content.
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { OverviewTab } from "@/components/lab-builder/overview";
import { PreviewTab } from "@/components/lab-builder/preview";
import { ScriptsTab } from "@/components/lab-builder/scripts";
import { StartingStateTab } from "@/components/lab-builder/starting-state";
import { TasksTab } from "@/components/lab-builder/tasks";
import { TestPublishTab } from "@/components/lab-builder/test-publish";
import { ValidationPanel } from "@/components/lab-builder/validation";
import { YamlTab } from "@/components/lab-builder/yaml";
import { Shell } from "@/components/shell";
import { ErrorBanner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { type Catalogue, type Content, type Draft, type ErrorRow, type Lab, STATUS_LABEL, STATUS_PILL,
  type Validation } from "@/lib/builder";

const TABS = [
  { id: "overview", label: "Overview" }, { id: "tasks", label: "Tasks" }, { id: "start", label: "Starting state" },
  { id: "scripts", label: "Scripts" }, { id: "yaml", label: "YAML" }, { id: "preview", label: "Preview" },
  { id: "test", label: "Test & publish" },
] as const;
type Tab = (typeof TABS)[number]["id"];
const SAVE_FIRST: Tab[] = ["yaml", "preview", "test"];  // these show the saved draft

const AUTOSAVE_MS = 800;      // quiet period after the last keystroke before saving
const COALESCE_MS = 900;      // edits closer together than this become one undo step
const HISTORY_MAX = 100;

type SavePhase = "idle" | "pending" | "saving" | "saved" | "error";
type History = { stack: Content[]; idx: number };

export default function DraftEditor() {
  const { id } = useParams<{ id: string }>();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [content, setContent] = useState<Content | null>(null);
  const [dirty, setDirty] = useState(false);
  const [rev, setRev] = useState(0);  // bumps when content is replaced from the server (YAML reload)
  const [formKey, setFormKey] = useState(0);  // remounts the form (server replace, undo, redo)
  const [hist, setHist] = useState<History>({ stack: [], idx: -1 });
  const [catalogue, setCatalogue] = useState<Catalogue | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [focusTask, setFocusTask] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [phase, setPhase] = useState<SavePhase>("idle");
  const [stale, setStale] = useState<ApiError | null>(null);
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const contentRef = useRef<Content | null>(null);
  contentRef.current = content;
  const dirtyRef = useRef(false);
  dirtyRef.current = dirty;
  const draftRef = useRef<Draft | null>(null);
  draftRef.current = draft;
  const histRef = useRef<History>(hist);
  histRef.current = hist;
  const staleRef = useRef(false);
  staleRef.current = stale !== null;
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastEditAtRef = useRef(0);
  const lastOpRef = useRef<"edit" | "nav">("nav");
  const saveRef = useRef<() => Promise<Draft | null>>(async () => null);

  const replace = useCallback((d: Draft) => {
    setDraft(d); setContent(d.content); setDirty(false); setStale(null);
    setRev((r) => r + 1); setFormKey((k) => k + 1);
    const h = { stack: [d.content], idx: 0 };   // a fresh baseline: undo goes back no further
    histRef.current = h; setHist(h);
    lastEditAtRef.current = 0; lastOpRef.current = "nav";
    setPhase("idle");
  }, []);

  const load = useCallback(async () => {
    try { replace(await api<Draft>(`/api/instructor/builder/drafts/${id}`)); } catch (e) { setError(e); }
  }, [id, replace]);

  /** Preview status only — a full reload would throw away the undo history and any unsaved edits. */
  const refreshPreview = useCallback(async () => {
    try {
      const p = await api<{ preview: { status: string } }>(`/api/instructor/builder/drafts/${id}/preview-sandbox`);
      setDraft((d) => (d ? { ...d, preview_status: p.preview.status } : d));
    } catch { /* a stopped preview is not an error worth surfacing here */ }
  }, [id]);

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

  const schedule = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => { timerRef.current = null; void saveRef.current(); }, AUTOSAVE_MS);
  }, []);

  const save = useCallback(async (): Promise<Draft | null> => {
    const d0 = draftRef.current;
    const c = contentRef.current;
    if (!d0 || !c) return null;
    if (d0.status === "testing" || d0.status === "published") return null;  // locked: never autosave over it
    if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
    setSaving(true); setPhase("saving"); setStale(null);
    try {
      const files: Record<string, string> = {};
      for (const n of d0.editable_files) files[n] = c.files[n] ?? "";
      const d = await api<Draft>(`/api/instructor/builder/drafts/${d0.id}`, {
        method: "PUT", body: { lab: c.lab, files, base_rev: d0.rev },
      });
      setDraft(d);
      const typed = contentRef.current !== c;   // something changed while the request was in flight
      setDirty(typed);
      setPhase(typed ? "pending" : "saved");
      if (typed && !staleRef.current) schedule();
      return d;
    } catch (e) {
      if (e instanceof ApiError && e.code === "stale_revision") {
        // Somebody saved newer content: stop autosaving rather than overwrite it.
        setStale(e); setPhase("error");
      } else {
        setError(e); setPhase("error");   // no automatic retry: the next edit schedules the next attempt
      }
      return null;
    } finally {
      setSaving(false);
    }
  }, [schedule]);
  saveRef.current = save;

  /** Record the content a step can be undone to. A burst of keystrokes inside COALESCE_MS collapses into
   * one undo step, so Ctrl+Z removes the burst rather than one character. */
  const remember = (next: Content) => {
    const h = histRef.current;
    const now = Date.now();
    const coalesce = lastOpRef.current === "edit" && h.idx > 0 && now - lastEditAtRef.current < COALESCE_MS;
    lastEditAtRef.current = now;
    lastOpRef.current = "edit";
    let out: History;
    if (coalesce) {
      const stack = h.stack.slice(0, h.idx + 1);
      stack[h.idx] = next;                 // the burst's earlier states collapse into this one
      out = { stack, idx: h.idx };
    } else {
      const stack = h.stack.slice(0, h.idx + 1).concat([next]);
      const drop = Math.max(0, stack.length - HISTORY_MAX);
      out = { stack: stack.slice(drop), idx: stack.length - 1 - drop };
    }
    histRef.current = out;
    setHist(out);
  };

  const edit = (fn: (c: Content) => Content) => {
    const cur = contentRef.current;
    if (!cur) return;
    const next = fn(cur);
    if (next === cur) return;
    contentRef.current = next;
    setContent(next);
    remember(next);
    setDirty(true); dirtyRef.current = true;
    setPhase((p) => (p === "saving" ? "saving" : "pending"));
    if (!staleRef.current) schedule();
  };
  const setLab = (lab: Lab) => edit((c) => ({ ...c, lab }));
  const setFile = (name: string, text: string) => edit((c) => ({ ...c, files: { ...c.files, [name]: text } }));

  const step = useCallback((delta: number) => {
    const h = histRef.current;
    const idx = h.idx + delta;
    if (idx < 0 || idx >= h.stack.length) return;
    const next = h.stack[idx];
    lastOpRef.current = "nav"; lastEditAtRef.current = 0;
    histRef.current = { ...h, idx };
    setHist(histRef.current);
    contentRef.current = next;
    setContent(next);
    setDirty(true); dirtyRef.current = true;
    setFormKey((k) => k + 1);       // remount: no tab keeps local state from the discarded content
    setPhase("pending");
    if (!staleRef.current) schedule();
  }, [schedule]);
  const undo = useCallback(() => step(-1), [step]);
  const redo = useCallback(() => step(1), [step]);

  // Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z and Ctrl/Cmd+Y — but never inside a text field, where the browser's own
  // undo is what the author expects.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      if (!(e.metaKey || e.ctrlKey)) return;
      const k = e.key.toLowerCase();
      if (k === "z" && !e.shiftKey) { e.preventDefault(); undo(); }
      else if ((k === "z" && e.shiftKey) || k === "y") { e.preventDefault(); redo(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo]);

  // Leaving the page (SPA navigation) with unsaved work: flush what we have. Best effort by design —
  // the beforeunload guard above still covers closing the tab mid-save.
  useEffect(() => () => { if (dirtyRef.current) void save(); }, [save]);

  async function go(next: Tab) {
    if (SAVE_FIRST.includes(next) && dirtyRef.current && !(await save())) return;
    if (next === "tasks") void refreshPreview();   // "Run this check" needs the current preview state
    setTab(next);
  }

  async function revalidate() {
    if (!draft) return;
    setValidating(true);
    try {
      if (dirtyRef.current) await save();
      else {
        const v = await api<Validation>(`/api/instructor/builder/drafts/${draft.id}/validate`, { method: "POST" });
        setDraft({ ...draftRef.current!, validation: v });
      }
    } catch (e) { setError(e); } finally { setValidating(false); }
  }

  function jump(row: ErrorRow) {
    if (row.break_action != null) void go("start");
    else if (row.task) { setFocusTask(row.task); void go("tasks"); setTimeout(() => document.getElementById(`task-${row.task}`)?.scrollIntoView({ block: "start", behavior: "smooth" }), 50); }
    else if (row.loc?.startsWith("private/") || row.loc?.startsWith("public/") || row.message.startsWith("private/")) void go("scripts");
    else void go("overview");
  }

  async function runTest() {
    if (!draftRef.current) return;
    const saved = dirtyRef.current ? await save() : draftRef.current;
    if (!saved) return;
    setDraft(await api<Draft>(`/api/instructor/builder/drafts/${saved.id}/test`, { method: "POST" }));
  }

  if (!draft || !content) {
    return <Shell><ErrorBanner error={error} onRetry={() => void load()} />{!error && <p className="muted"><span className="spinner" /> Loading…</p>}</Shell>;
  }
  const readOnly = draft.status === "testing" || draft.status === "published";
  const lab = content.lab;
  const canUndo = hist.idx > 0;
  const canRedo = hist.idx >= 0 && hist.idx < hist.stack.length - 1;
  const stateChip = phase === "error" ? (
    <span className="small lb-save fail" role="status" data-testid="save-state">Save failed</span>
  ) : phase === "saving" ? (
    <span className="small lb-save" role="status" data-testid="save-state"><span className="spinner" /> Saving…</span>
  ) : dirty ? (
    <span className="small lb-save warn" role="status" data-testid="save-state">Unsaved changes</span>
  ) : phase === "saved" ? (
    <span className="small lb-save pass" role="status" data-testid="save-state">Saved</span>
  ) : null;

  return (
    <Shell>
      <div className="stack" style={{ gap: 16 }}>
        <div className="row between" style={{ alignItems: "flex-end" }}>
          <div>
            <Link href="/instructor/labs" className="small">← Labs</Link>
            <div className="eyebrow" style={{ marginTop: 10 }}>Lab draft · <span className="mono">{lab.id}@{lab.version}</span></div>
            <h1 data-testid="draft-title">{lab.title || "Untitled lab"}</h1>
          </div>
          <div className="row" style={{ alignItems: "center" }}>
            <span className={`pill ${STATUS_PILL[draft.status]}`} data-testid="draft-status">{STATUS_LABEL[draft.status]}</span>
            {stateChip}
            <button className="ghost" onClick={undo} disabled={!canUndo || readOnly} title="Undo (Ctrl/Cmd+Z)"
              data-testid="undo-draft" aria-label="Undo">↶ Undo</button>
            <button className="ghost" onClick={redo} disabled={!canRedo || readOnly} title="Redo (Ctrl/Cmd+Shift+Z)"
              data-testid="redo-draft" aria-label="Redo">↷ Redo</button>
            <button className="primary" onClick={() => void save()}
              disabled={!dirty || saving || readOnly} data-testid="save-draft">
              {saving ? <><span className="spinner" /> Saving…</> : "Save"}</button>
          </div>
        </div>

        {stale && (
          <div className="banner warn small" data-testid="stale-banner" role="alert">
            <div><strong>This draft was changed somewhere else</strong> — another tab, or a test run. Your
              edits are still here but were not saved, so the newer version isn&apos;t overwritten. Reload to
              carry on with that version.</div>
            <button onClick={() => void load()} data-testid="stale-reload">Reload draft</button>
          </div>
        )}
        {phase === "error" && !stale && (
          <div className="banner fail small" data-testid="save-failed" role="alert">
            <div>Your last change was not saved.</div>
            <button onClick={() => void save()} data-testid="save-retry">Try again</button>
          </div>
        )}
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
              {(tab === "overview" || tab === "tasks" || tab === "start" || tab === "scripts") && (
                <fieldset disabled={readOnly} className="lb-plain" key={formKey}>
                  {tab === "overview" && <OverviewTab lab={lab} catalogue={catalogue} validation={draft.validation} onChange={setLab} />}
                  {tab === "tasks" && <TasksTab lab={lab} catalogue={catalogue} validation={draft.validation} focusTask={focusTask}
                    draftId={draft.id} previewRunning={draft.preview_status === "running"} onChange={setLab} />}
                  {tab === "start" && <StartingStateTab lab={lab} draftId={draft.id} validation={draft.validation} onChange={setLab} />}
                  {tab === "scripts" && <ScriptsTab content={content} readOnlyFiles={draft.read_only_files} validation={draft.validation} onFile={setFile} />}
                </fieldset>
              )}
              {tab === "yaml" && <YamlTab draftId={draft.id} baseRev={draft.rev} rev={rev} readOnly={readOnly}
                onApplied={replace} onReload={() => void load()} />}
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
        .lb-save { display: inline-flex; align-items: center; gap: 6px; font-weight: 600; }
        .lb-save.warn { color: var(--warn); }
        .lb-save.pass { color: var(--pass); }
        .lb-save.fail { color: var(--fail); }
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
