export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function fmtDuration(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
}

export function pct(score: string | null, max: string): number {
  if (score === null) return 0;
  const m = Number(max);
  return m ? Math.round((Number(score) / m) * 100) : 0;
}

export const TRIGGER_LABEL: Record<string, string> = {
  submit: "Submitted",
  ttl: "Auto-submitted: time ran out",
  idle: "Auto-submitted: inactive",
  close: "Auto-submitted: lab closed",
  staff: "Ended by instructor",
};

export const FAILURE_TEXT: Record<string, string> = {
  provision_error: "Your lab couldn't start.",
  provision_timeout: "Your lab took too long to start.",
  capacity_full: "All lab seats were in use when your lab tried to start.",
  sandbox_lost: "Your sandbox stopped unexpectedly.",
  sandbox_oom: "Your sandbox ran out of memory.",
  reset_failed: "Resetting your lab failed.",
  reset_timeout: "Resetting your lab took too long.",
  grading_failed: "Grading failed, so this attempt wasn't counted.",
  admin_kill: "An administrator ended this lab.",
  staff_terminated: "Your instructor ended this lab without grading it.",
  runner_lost: "The server running your lab stopped responding. This attempt wasn't counted; start the lab again.",
};
