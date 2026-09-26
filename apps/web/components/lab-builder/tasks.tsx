"use client";
import { useRef } from "react";
import { ListEditor, SchemaForm } from "@/components/schema-form";
import { type Catalogue, type Check, type CheckType, COMMON_KEYS, defaultParams, errorsFor, type Lab, type Task,
  type Validation } from "@/lib/builder";
import { ErrorList } from "./validation";

function move<T>(xs: T[], i: number, d: number): T[] {
  const j = i + d;
  if (j < 0 || j >= xs.length) return xs;
  const out = [...xs];
  [out[i], out[j]] = [out[j], out[i]];
  return out;
}

let seq = 0;
/** Stable React keys for a reorderable list, so editors with local state (key-value rows, JSON) follow their
 * item when items move or are removed. */
function useStableKeys(length: number) {
  const keys = useRef<string[]>([]);
  while (keys.current.length < length) keys.current.push(`k${++seq}`);
  if (keys.current.length > length) keys.current.length = length;
  return {
    keys: keys.current,
    remove: (i: number) => { keys.current.splice(i, 1); },
    move: (i: number, d: number) => { keys.current = move(keys.current, i, d); },
  };
}

function newTaskId(tasks: Task[]): string {
  const ids = new Set(tasks.map((t) => t.id));
  let n = tasks.length + 1;
  while (ids.has(`task-${n}`)) n++;
  return `task-${n}`;
}

export function TasksTab({ lab, catalogue, validation, focusTask, onChange }: {
  lab: Lab; catalogue: Catalogue | null; validation: Validation | null; focusTask: string | null; onChange: (lab: Lab) => void;
}) {
  const tasks = lab.tasks ?? [];
  const setTasks = (next: Task[]) => onChange({ ...lab, tasks: next });
  const setTask = (i: number, t: Task) => setTasks(tasks.map((x, j) => (i === j ? t : x)));
  const tk = useStableKeys(tasks.length);
  const firstType = catalogue?.check_types.find((c) => lab.services?.includes(c.service) && c.supported) ?? catalogue?.check_types[0];

  function addTask() {
    const check: Check = firstType ? { type: firstType.type, ...defaultParams(firstType.params_schema) } : { type: "s3.bucket_exists" };
    setTasks([...tasks, { id: newTaskId(tasks), title: "New task", hints: [], marks: 10, checks: [check] }]);
  }

  const total = tasks.reduce((s, t) => s + (Number(t.marks) || 0), 0);
  return (
    <div className="stack" style={{ gap: 16 }}>
      <p className="small muted" style={{ margin: 0 }}>{tasks.length} {tasks.length === 1 ? "task" : "tasks"} · {total} marks in total.
        A task scores its marks when all of its checks pass (or in proportion to the passing checks&apos; weights).</p>
      {tasks.map((t, i) => (
        <TaskCard key={tk.keys[i]} task={t} index={i} count={tasks.length} lab={lab} catalogue={catalogue} validation={validation}
          focused={focusTask === t.id}
          onChange={(nt) => setTask(i, nt)} onMove={(d) => { tk.move(i, d); setTasks(move(tasks, i, d)); }}
          onRemove={() => { tk.remove(i); setTasks(tasks.filter((_, j) => j !== i)); }} />
      ))}
      <div><button onClick={addTask} data-testid="add-task">+ Add task</button></div>
    </div>
  );
}

function TaskCard({ task, index, count, lab, catalogue, validation, focused, onChange, onMove, onRemove }: {
  task: Task; index: number; count: number; lab: Lab; catalogue: Catalogue | null; validation: Validation | null; focused: boolean;
  onChange: (t: Task) => void; onMove: (d: number) => void; onRemove: () => void;
}) {
  const set = <K extends keyof Task>(k: K, v: Task[K]) => onChange({ ...task, [k]: v });
  const checks = task.checks ?? [];
  const setCheck = (i: number, c: Check) => set("checks", checks.map((x, j) => (i === j ? c : x)));
  const ck = useStableKeys(checks.length);
  const addCheck = () => {
    const ct = catalogue?.check_types.find((c) => lab.services?.includes(c.service) && c.supported);
    set("checks", [...checks, ct ? { type: ct.type, ...defaultParams(ct.params_schema) } : { type: "" }]);
  };
  return (
    <section className={`card flat lb-task ${focused ? "lb-focus" : ""}`} data-testid="task-card" id={`task-${task.id}`}>
      <div className="row between">
        <h3>Task {index + 1}</h3>
        <div className="row" style={{ gap: 4 }}>
          <button className="small ghost" onClick={() => onMove(-1)} disabled={index === 0} aria-label="Move task up">↑</button>
          <button className="small ghost" onClick={() => onMove(1)} disabled={index === count - 1} aria-label="Move task down">↓</button>
          <button className="small ghost danger" onClick={onRemove} disabled={count === 1}>Remove task</button>
        </div>
      </div>
      <div className="lb-grid" style={{ marginTop: 10 }}>
        <label className="lb-wide">Title<input value={task.title ?? ""} maxLength={200} data-testid="task-title"
          onChange={(e) => set("title", e.target.value)} /></label>
        <label>Task id<input className="mono" value={task.id ?? ""} data-testid="task-id" onChange={(e) => set("id", e.target.value)} /></label>
        <label>Marks<input type="number" min={0.01} max={1000} step="any" value={task.marks ?? ""} data-testid="task-marks"
          onChange={(e) => set("marks", e.target.value === "" ? "" : Number(e.target.value))} /></label>
        <label>Scoring<select value={task.scoring ?? "all"} onChange={(e) => set("scoring", e.target.value as Task["scoring"])}>
          <option value="all">All checks must pass</option><option value="proportional">Proportional to passing checks</option></select></label>
        <label className="lb-wide">Description<textarea rows={3} maxLength={4000} value={task.description ?? ""}
          onChange={(e) => set("description", e.target.value)} placeholder="Optional instructions shown under the task" /></label>
      </div>
      <div style={{ marginTop: 10 }}>
        <div className="lb-sub">Hints</div>
        <ListEditor values={task.hints ?? []} placeholder="A hint students can reveal" onChange={(rows) => set("hints", rows)} />
      </div>
      <ErrorList rows={errorsFor(validation, task.id, null)} />
      <div className="lb-sub" style={{ marginTop: 14 }}>Checks</div>
      <div className="stack">
        {checks.map((c, i) => (
          <CheckEditor key={ck.keys[i]} check={c} index={i} task={task} labEngine={lab.runtime?.emulator ?? "default"} catalogue={catalogue} validation={validation}
            onChange={(nc) => setCheck(i, nc)} onRemove={() => { ck.remove(i); set("checks", checks.filter((_, j) => j !== i)); }}
            onMove={(d) => { ck.move(i, d); set("checks", move(checks, i, d)); }} count={checks.length} />
        ))}
        <div><button className="small" onClick={addCheck} data-testid="add-check">+ Add check</button></div>
      </div>
    </section>
  );
}

function splitCheck(c: Check): { common: Partial<Check>; params: Record<string, unknown> } {
  const common: Partial<Check> = {};
  const params: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(c)) {
    if ((COMMON_KEYS as readonly string[]).includes(k)) (common as Record<string, unknown>)[k] = v;
    else params[k] = v;
  }
  return { common, params };
}

function CheckEditor({ check, index, count, task, labEngine, catalogue, validation, onChange, onRemove, onMove }: {
  check: Check; index: number; count: number; task: Task; labEngine: string; catalogue: Catalogue | null; validation: Validation | null;
  onChange: (c: Check) => void; onRemove: () => void; onMove: (d: number) => void;
}) {
  const ct: CheckType | undefined = catalogue?.check_types.find((c) => c.type === check.type);
  const { common, params } = splitCheck(check);
  const setCommon = (k: "hidden" | "weight" | "feedback", v: unknown) => {
    const next: Record<string, unknown> = { ...check };
    if (v === undefined || v === "" || v === null) delete next[k];
    else next[k] = v;
    onChange(next as Check);
  };
  const byService = new Map<string, CheckType[]>();
  for (const c of catalogue?.check_types ?? []) byService.set(c.service, [...(byService.get(c.service) ?? []), c]);
  // Only engines this lab can run on matter: every primary engine for "default", else the pinned one.
  const pinned = labEngine !== "default" ? [labEngine] : catalogue?.engines.primary ?? [];
  const unusable = ct ? Object.entries(ct.engines).filter(([n, e]) => pinned.includes(n) && !e.usable).map(([n]) => n) : [];
  return (
    <div className="lb-check" data-testid="check-card">
      <div className="row between" style={{ flexWrap: "nowrap" }}>
        <label className="grow" style={{ maxWidth: 380 }}>Check {index + 1}
          <select value={check.type} data-testid="check-type"
            onChange={(e) => {
              const nt = catalogue?.check_types.find((c) => c.type === e.target.value);
              onChange({ ...common, type: e.target.value, ...(nt ? defaultParams(nt.params_schema) : {}) } as Check);
            }}>
            {!ct && <option value={check.type}>{check.type || "Choose a check"}</option>}
            {[...byService.entries()].map(([svc, types]) => (
              <optgroup key={svc} label={svc.toUpperCase()}>
                {types.map((t) => <option key={t.type} value={t.type} disabled={!t.supported}>{t.type}{t.supported ? "" : " (unavailable)"}</option>)}
              </optgroup>
            ))}
          </select>
        </label>
        <div className="row" style={{ gap: 4, alignSelf: "flex-end" }}>
          <button className="small ghost" onClick={() => onMove(-1)} disabled={index === 0} aria-label="Move check up">↑</button>
          <button className="small ghost" onClick={() => onMove(1)} disabled={index === count - 1} aria-label="Move check down">↓</button>
          <button className="small ghost danger" onClick={onRemove} disabled={count === 1} aria-label={`Remove check ${index + 1}`}>✕</button>
        </div>
      </div>
      {ct && unusable.length > 0 && (
        <p className="small" style={{ color: "var(--warn)", margin: "6px 0 0" }}>Not available on {unusable.join(", ")}
          {ct.unsupported_reason ? `: ${ct.unsupported_reason}` : ""}.</p>
      )}
      {ct && <p className="lb-hint" style={{ margin: "6px 0 10px" }}>Reads {ct.reads.join(", ")}</p>}
      {ct ? (
        <SchemaForm key={check.type} schema={ct.params_schema} value={params} idPrefix={`t${task.id}-c${index}`}
          onChange={(p) => onChange({ ...common, type: check.type, ...p } as Check)} />
      ) : <p className="small muted">Unknown check type. Choose one from the list.</p>}
      <div className="row" style={{ marginTop: 10, alignItems: "flex-end" }}>
        <label className="lb-inline"><input type="checkbox" checked={Boolean(check.hidden)} onChange={(e) => setCommon("hidden", e.target.checked || undefined)} />
          Hidden from students</label>
        <label style={{ width: 120 }}>Weight<input type="number" min={1} max={100} value={check.weight ?? ""} placeholder="1"
          onChange={(e) => setCommon("weight", e.target.value === "" ? undefined : Number(e.target.value))} /></label>
        <label className="grow">Feedback when it fails<input maxLength={500} value={check.feedback ?? ""} placeholder="Default: the check's own message"
          onChange={(e) => setCommon("feedback", e.target.value)} /></label>
      </div>
      <ErrorList rows={errorsFor(validation, task.id, index + 1)} />
    </div>
  );
}
