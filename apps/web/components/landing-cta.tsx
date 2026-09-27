"use client";
// Session-aware calls to action for the public landing page. The page itself stays a server component; only
// these fragments read the current session, so a signed-in visitor sees their name (and a way back to the
// app) instead of "Sign in" / "Try the demo". While the session is loading we render the anonymous CTAs,
// which is also what anonymous visitors keep seeing — the swap is invisible unless you are signed in.
import Link from "next/link";
import { homeFor, useAuth } from "./auth";
import type { Me } from "@/lib/types";

function homeLabel(me: Me): string {
  return me.role === "student" ? "Go to my labs"
    : me.role === "instructor" ? "Go to my courses"
      : "Go to runtime";
}

/** Header CTA area: sign-in buttons for visitors, name + app link for signed-in users. */
export function LandingNavCtas() {
  const { me, loading } = useAuth();
  if (loading || !me) {
    return (
      <div className="lp-nav-cta">
        <Link href="/login" className="lp-btn ghost">Sign in</Link>
        <Link href="/login" className="lp-btn primary" data-testid="cta-try">Try the demo</Link>
      </div>
    );
  }
  return (
    <div className="lp-nav-cta">
      <Link href={homeFor(me)} className="lp-who" data-testid="landing-user">{me.name} · {me.role}</Link>
      <Link href={homeFor(me)} className="lp-btn primary" data-testid="nav-cta-home">{homeLabel(me)}</Link>
    </div>
  );
}

/** Hero / final CTA row: "Try the demo" + "For instructors" for visitors, one app link for signed-in users. */
export function LandingPrimaryCtas({ center = false, testId = "cta", instructorTestId }:
  { center?: boolean; testId?: string; instructorTestId?: string }) {
  const { me, loading } = useAuth();
  if (loading || !me) {
    return (
      <div className={center ? "lp-ctas center" : "lp-ctas"}>
        <Link href="/login" className="lp-btn primary lg" data-testid={testId}>Try the demo</Link>
        <Link href="/login?next=/instructor" className="lp-btn outline lg" data-testid={instructorTestId}>For instructors</Link>
      </div>
    );
  }
  return (
    <div className={center ? "lp-ctas center" : "lp-ctas"}>
      <Link href={homeFor(me)} className="lp-btn primary lg" data-testid={`${testId}-home`}>{homeLabel(me)}</Link>
    </div>
  );
}
