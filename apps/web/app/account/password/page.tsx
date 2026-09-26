"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { homeFor, useAuth } from "@/components/auth";
import { Shell } from "@/components/shell";
import { ErrorBanner } from "@/components/ui";
import { api } from "@/lib/api";
import type { Me } from "@/lib/types";

export default function ChangePassword() {
  const { me, reload } = useAuth();
  const router = useRouter();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const mismatch = again.length > 0 && next !== again;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const u = await api<Me>("/api/auth/change-password", { method: "POST", body: { current_password: current, new_password: next } });
      await reload();
      router.replace(homeFor(u));
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  return (
    <Shell>
      <form className="card stack" onSubmit={submit} style={{ maxWidth: 440, margin: "20px auto" }}>
        <div><div className="eyebrow">Your account</div><h1 style={{ fontSize: 24 }}>Choose a new password</h1></div>
        {me?.must_change_password && (
          <div className="banner info small">You signed in with a temporary password from your instructor. Choose your own password to continue.</div>)}
        <label>{me?.must_change_password ? "Temporary password" : "Current password"}
          <input type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} data-testid="current-password" /></label>
        <label>New password<input type="password" autoComplete="new-password" required minLength={10} value={next} onChange={(e) => setNext(e.target.value)} data-testid="new-password" />
          <span className="small muted" style={{ fontWeight: 400 }}>At least 10 characters.</span></label>
        <label>Repeat new password<input type="password" autoComplete="new-password" required value={again} onChange={(e) => setAgain(e.target.value)} data-testid="repeat-password" /></label>
        {mismatch && <span className="small" style={{ color: "var(--fail)" }}>The two new passwords don&apos;t match.</span>}
        <ErrorBanner error={error} />
        <button className="primary" disabled={busy || mismatch || next.length < 10} data-testid="save-password">{busy ? "Saving…" : "Save password"}</button>
      </form>
    </Shell>
  );
}
