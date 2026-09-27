// Lab Builder (phase 8) types and helpers. Shapes mirror services/api/app/instructor/builder.py.

export type JsonSchema = {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  const?: unknown;
  pattern?: string;
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  items?: JsonSchema;
  properties?: Record<string, JsonSchema>;
  additionalProperties?: boolean | JsonSchema;
  required?: string[];
  anyOf?: JsonSchema[];
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
};

export type CheckType = {
  type: string;
  service: string;
  params_schema: JsonSchema;
  reads: string[];
  supported: boolean;
  unsupported_reason: string | null;
  engines: Record<string, { usable: boolean; unusable_ops: string[] }>;
};

export type Catalogue = {
  check_types: CheckType[];
  common_fields: JsonSchema;
  services: string[];
  engines: { primary: string[]; specialised: string[] };
  editable_files: string[];
};

export type ErrorRow = { message: string; loc: string | null; task: string | null; check: number | null;
  field: string | null; break_action?: number | null };
export type Validation = { ok: boolean; errors: ErrorRow[]; content_sha256: string | null; validated_at?: string };

export type CheckResult = {
  task: string; check: string; params: Record<string, unknown>; expected: unknown; actual: unknown;
  passed: boolean; hidden: boolean; message: string; marks_awarded: string; marks_possible: string;
};
export type ScenarioOut = {
  name: string; engine: string; scenario: string; expected: string; actual: string | null; ok: boolean; detail: string;
  tasks: { task_id: string; title: string; marks_awarded: string; marks_possible: string; passed: boolean; checks: CheckResult[] }[];
};
export type LastTest = {
  id: string; status: "running" | "passed" | "failed" | "error"; content_sha256: string; started_at: string;
  finished_at: string | null; expected: Record<string, string>; plan: string[]; scenarios: ScenarioOut[]; error: string | null;
};

export type DraftStatus = "draft" | "testing" | "passed" | "failed" | "published";
export type Check = { type: string; hidden?: boolean; weight?: number; feedback?: string | null; [param: string]: unknown };
export type Task = { id: string; title: string; description?: string; hints?: string[]; marks: number | string;
  scoring?: "all" | "proportional"; checks: Check[] };
export type BreakAction = { type: string; [param: string]: unknown };
export type Lab = {
  schema_version: number; id: string; version: string; title: string; kind?: string; summary?: string; story?: string;
  services: string[]; runtime?: { emulator?: string }; duration_minutes: number; idle_minutes?: number | null;
  max_attempts?: number; variables?: Record<string, string>; requires?: string[]; setup?: { script: string; timeout_s?: number } | null;
  break_actions?: BreakAction[]; baseline?: { expected_score: number | string } | null;
  tasks: Task[]; [other: string]: unknown;
};
export type Content = { lab: Lab; files: Record<string, string> };

export type Draft = {
  id: string; slug: string; title: string; status: DraftStatus; owner: { id: string; name: string | null };
  base_lab_version_id: string | null; published_version_id: string | null; validation: Validation | null;
  tested_sha256: string | null; created_at: string; updated_at: string;
  content: Content; last_test: LastTest | null; editable_files: string[]; read_only_files: string[];
};
export type DraftSummary = Omit<Draft, "content" | "last_test" | "editable_files" | "read_only_files">;

export type LabVersionRow = {
  id: string; lab: string; lab_id: string; title: string; version: string; content_sha256: string; created_at: string;
  builtin: boolean; shared: boolean; mine: boolean; owner: { id: string; name: string | null } | null;
};

/** A curated starting point (phase 9, milestone 40): a working built-in lab offered as a template. */
export type Template = {
  id: string; title: string; summary: string; services: string[]; difficulty: "starter" | "intermediate" | "advanced";
  highlights: string[]; source_lab_id: string; available: boolean; latest_version: string | null;
};

/** The interactive preview sandbox of a draft (phase 9 M42). It is not a session: no attempt or grade. */
export type PreviewSandbox = {
  status: "running" | "stopped";
  sandbox_id: string | null;
  engine: string | null;
  started_at: string | null;
  last_active: string | null;
  error: string | null;
  ws_path: string;
  console: string | null;
  terminal_ticket: string | null;
};

/** The publish-readiness checklist (M42): exactly what the publish gate requires, one row each. */
export type ReadinessCheck = { id: string; label: string; ok: boolean; detail: string | null; errors: ErrorRow[] };
export type Readiness = { ready: boolean; checks: ReadinessCheck[] };

export type PreviewTask = { id: string; title: string; description: string; hints: string[]; marks: string };
export type Preview = {
  lab: { id: string; version: string; title: string; summary: string; story: string; services: string[]; kind: string;
    duration_minutes: number; max_score: string; tasks: PreviewTask[] };
  variables: Record<string, string>;
};

export const STATUS_LABEL: Record<DraftStatus, string> = {
  draft: "Draft", testing: "Testing…", passed: "Test passed", failed: "Test failed", published: "Published",
};
export const STATUS_PILL: Record<DraftStatus, string> = {
  draft: "", testing: "info", passed: "pass", failed: "fail", published: "pass",
};

export const COMMON_KEYS = ["type", "hidden", "weight", "feedback"] as const;

/** Resolve a local `$ref` against the root schema's `$defs`. */
export function deref(s: JsonSchema, root: JsonSchema): JsonSchema {
  if (s.$ref) {
    const name = s.$ref.split("/").pop() ?? "";
    return deref(root.$defs?.[name] ?? {}, root);
  }
  return s;
}

/** A field's effective schema: `$ref` resolved and `anyOf [X, null]` collapsed to X (nullable). */
export function effective(s: JsonSchema, root: JsonSchema): { schema: JsonSchema; nullable: boolean } {
  const d = deref(s, root);
  if (d.anyOf) {
    const branches = d.anyOf.map((b) => deref(b, root));
    const nonNull = branches.filter((b) => b.type !== "null");
    const nullable = nonNull.length < branches.length;
    if (nonNull.length === 1) return { schema: { ...nonNull[0], title: d.title, default: d.default, description: d.description }, nullable };
    return { schema: { ...d, anyOf: nonNull }, nullable };
  }
  return { schema: d, nullable: false };
}

/** Starting parameters for a new check: every required field's default, or an empty value of its type. */
export function defaultParams(schema: JsonSchema): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const key of schema.required ?? []) {
    const { schema: f } = effective(schema.properties?.[key] ?? {}, schema);
    if (f.default !== undefined) out[key] = f.default;
    else if (f.enum?.length) out[key] = f.enum[0];
    else if (f.type === "boolean") out[key] = false;
    else if (f.type === "object") out[key] = {};
    else if (f.type === "array") out[key] = [];
    else if (f.type === "string") out[key] = "";
  }
  return out;
}

/** Parse a free-form scalar typed by the author ("42", "true", "text"). */
export function parseScalar(v: string): unknown {
  const t = v.trim();
  if (t === "") return "";
  try {
    const j = JSON.parse(t);
    if (j === null || ["number", "boolean", "string"].includes(typeof j)) return j;
  } catch { /* plain text */ }
  return v;
}

export const showScalar = (v: unknown) => (typeof v === "string" ? v : v === undefined || v === null ? "" : JSON.stringify(v));

export function maxScore(lab: Lab): number {
  return (lab.tasks ?? []).reduce((s, t) => s + (Number(t.marks) || 0), 0);
}

/** The partial score in private/expected.yaml, if the file is the simple `key: value` form the builder writes. */
export function readExpected(text: string | undefined): { partial: string; simple: boolean } {
  if (!text) return { partial: "", simple: true };
  let partial = "";
  let simple = true;
  for (const line of text.split("\n")) {
    const t = line.trim();
    if (!t || t.startsWith("#")) continue;
    const m = t.match(/^(empty|partial|solution)\s*:\s*"?([0-9.]+)"?\s*$/);
    if (!m) { simple = false; continue; }
    if (m[1] === "partial") partial = m[2];
  }
  return { partial, simple };
}

/** expected.yaml written by the builder: empty is always 0 and the solution defaults to full marks. */
export function writeExpected(partial: string): string {
  return `# Scores the test run must produce (PRIVATE). The solution must reach full marks.\nempty: "0.00"\n`
    + (partial.trim() ? `partial: "${partial.trim()}"\n` : "");
}

/** Validation rows for one task (check = null) or one of its checks (1-based, as the API reports them). */
export function errorsFor(v: Validation | null, task: string, check: number | null): ErrorRow[] {
  return (v?.errors ?? []).filter((e) => e.task === task && (check === null ? !e.check : e.check === check));
}

export function rowLabel(e: ErrorRow): string {
  if (e.break_action != null) return `Starting state · action ${e.break_action + 1}${e.field ? ` · ${e.field}` : ""}`;
  if (e.task && e.check) return `Task ${e.task} · check ${e.check}${e.field ? ` · ${e.field}` : ""}`;
  if (e.task) return `Task ${e.task}${e.field ? ` · ${e.field}` : ""}`;
  return e.loc ?? "Lab";
}
