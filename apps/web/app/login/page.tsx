"use client";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { homeFor, useAuth } from "@/components/auth";
import type { Me } from "@/lib/types";

function LoginForm() {
  const { me, reload } = useAuth();
  const router = useRouter();
  const next = useSearchParams().get("next");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (me?.must_change_password) router.replace("/account/password");
    else if (me) router.replace(next && next.startsWith("/") && !next.startsWith("//") && next !== "/login" ? next : homeFor(me));
  }, [me, next, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api<Me>("/api/auth/login", { method: "POST", body: { email, password } });
      await reload();
    } catch (err) {
      setError(err instanceof ApiError
        ? err.code === "rate_limited" ? "Too many attempts. Wait a minute, then try again." : "Email or password is incorrect."
        : "Can't reach CloudLabs. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <section className="login-art" aria-hidden>
        <div className="eyebrow" style={{ color: "#8fb3d9" }}>CloudLabs</div>
        <p className="login-quote">Build it for real.<br />Get marked on what you built.</p>
        <pre className="login-term">{`cloudlabs:~$ aws s3 mb s3://cafe-7k2q9x-site
make_bucket: cafe-7k2q9x-site
✓ Create the bucket            25 / 25`}</pre>
      </section>
      <section className="login-form">
        <form onSubmit={submit} className="stack" style={{ width: "min(360px, 100%)" }}>
          <h1>Sign in</h1>
          <p className="muted small" style={{ margin: 0 }}>Use the account your instructor gave you.</p>
          <label>Email<input type="email" autoComplete="username" required value={email}
            onChange={(e) => setEmail(e.target.value)} /></label>
          <label>Password<input type="password" autoComplete="current-password" required value={password}
            onChange={(e) => setPassword(e.target.value)} /></label>
          {error && <div className="banner fail" role="alert">{error}</div>}
          <button className="primary" type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        </form>
      </section>
      <style>{`
        .login { min-height: 100vh; display: grid; grid-template-columns: 1.1fr 1fr; }
        .login-art { background: var(--ink); color: #fff; padding: 56px; display: flex; flex-direction: column; justify-content: center; gap: 28px; }
        .login-quote { font-family: var(--font-display); font-size: 42px; line-height: 1.08; font-weight: 700; margin: 0; letter-spacing: -.02em; }
        .login-term { font-family: var(--font-mono); font-size: 14px; background: var(--terminal); color: #9fe3c4; padding: 18px; border-radius: 10px; margin: 0; border: 1px solid #22335a; white-space: pre-wrap; }
        .login-form { display: grid; place-items: center; padding: 32px 16px; }
        @media (max-width: 800px) { .login { grid-template-columns: 1fr; } .login-art { padding: 28px 16px; } .login-quote { font-size: 30px; } }
      `}</style>
    </main>
  );
}

export default function LoginPage() {
  return <Suspense><LoginForm /></Suspense>;
}
