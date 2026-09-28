export type Role = "student" | "instructor" | "admin";
export interface Me { id: string; email: string; name: string; role: Role; short_id: string; must_change_password?: boolean }

export interface AttemptSummary {
  id: string; attempt_no: number; trigger: "submit" | "idle" | "ttl" | "close" | "staff"; counts: boolean;
  late: boolean; score: string; max_score: string; created_at: string; regraded?: boolean;
}

export interface LabTask { id: string; title: string; description: string; hints: string[]; marks: string }
export interface LabView {
  id: string; version: string; title: string; summary: string; story: string; services: string[]; kind?: "guided" | "break_fix";
  duration_minutes: number; max_score: string; tasks: LabTask[];
}

export interface AssignmentCard {
  id: string; title: string; lab_title: string; summary: string; services: string[]; kind?: "guided" | "break_fix";
  duration_minutes: number; open_at: string; due_at: string; close_at: string; is_open: boolean;
  is_late: boolean; attempts_used: number; attempts_allowed: number; attempts_left: number;
  grade_policy: "best" | "latest"; final_score: string | null; max_score: string;
  active_session: { id: string; state: SessionState } | null; attempts: AttemptSummary[];
  course?: { id: string; code: string; title: string; leaderboard?: "off" | "anonymous" | "named" }; lab?: LabView;
}

export type SessionState = "REQUESTED" | "PROVISIONING" | "READY" | "RESETTING" | "SUBMITTING" |
  "SUBMITTED" | "TERMINATING" | "TERMINATED" | "FAILED";

export interface LabSession {
  id: string; assignment_id: string; state: SessionState; failure_reason: string | null;
  created_at: string; ready_at: string | null; expires_at: string | null;
  idle_deadline_at: string | null; idle_warning_at: string | null; server_time: string;
  ttl_minutes: number; idle_minutes: number; attempt_id: string | null; lab?: LabView;
}

export interface CheckView {
  hidden: boolean; passed: boolean; message: string; marks_awarded: string; marks_possible: string;
}export interface TaskResultView {
  task_id: string; title: string; passed: boolean; marks_awarded: string; marks_possible: string;
  checks: CheckView[];
}
export interface ResultView { score: string; max_score: string; tasks: TaskResultView[] }
export interface AttemptResult {
  attempt: { id: string; attempt_no: number; trigger: string; counts: boolean; late: boolean;
    assignment_id: string; created_at: string; regraded: boolean };
  result: ResultView;
  insights: import("@/components/architecture-diagram").Insights | null;
  badges: import("@/components/progress-card").BadgeView[];
}

// --- attempt diff (phase 10, M48) -----------------------------------------------------------
export type ChangeKind = "fixed" | "regressed" | "unchanged" | "added" | "removed";
/** One side of a comparison. `expected`/`actual` are instructor-only (PLAN §7b) and absent for students. */
export interface DiffSide {
  passed: boolean; message: string; marks_awarded: string; marks_possible: string;
  expected?: unknown; actual?: unknown;
}
export interface DiffCheck {
  check: string; label: string; hidden: boolean; change: ChangeKind;
  before: DiffSide | null; after: DiffSide | null;
}
export interface DiffTask {
  task_id: string; title: string;
  passed: { before: boolean | null; after: boolean | null };
  marks_awarded: { before: string | null; after: string | null };
  checks: DiffCheck[];
}
export interface AttemptHead {
  attempt_id: string; attempt_no: number; trigger: string; counts: boolean; late: boolean;
  created_at: string; score: string; max_score: string; regraded: boolean;
}
export interface AttemptDiff {
  first_attempt: boolean; previous: AttemptHead | null; current: AttemptHead;
  summary: { fixed: number; regressed: number; unchanged: number; added: number; removed: number;
    score_before: string | null; score_after: string | null; delta: string | null };
  tasks: DiffTask[];
}
