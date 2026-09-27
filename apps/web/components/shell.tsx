"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { homeFor, useAuth } from "./auth";

export function Shell({ children, wide = false }: { children: React.ReactNode; wide?: boolean }) {
  const { me, loading, logout } = useAuth();
  const path = usePathname();
  if (loading || !me) {
    return <div className="page muted" aria-busy="true"><span className="spinner" /> Loading…</div>;
  }
  const links = me.role === "student"
    ? [{ href: "/labs", label: "My labs" }]
    : me.role === "instructor"
      ? [{ href: "/instructor", label: "Courses" }, { href: "/instructor/labs", label: "Labs" }]
      : [{ href: "/instructor", label: "Courses" }, { href: "/instructor/labs", label: "Labs" }, { href: "/admin/status", label: "Runtime" },
        { href: "/admin/users", label: "Users" }, { href: "/admin/courses", label: "Courses & staff" }, { href: "/admin/audit", label: "Audit log" }];
  return (
    <>
      <header className="topbar">
        <Link href={homeFor(me)} className="brand"><span className="dot" aria-hidden />Stackora</Link>
        <nav aria-label="Main">
          {links.map((l) => (
            <Link key={l.href} href={l.href} aria-current={current(path, l.href, links) ? "page" : undefined}>{l.label}</Link>
          ))}
        </nav>
        <span className="spacer" />
        <span className="who">{me.name} · {me.role}</span>
        <button className="small" onClick={() => void logout()}>Sign out</button>
      </header>
      {wide ? children : <main className="page">{children}</main>}
    </>
  );
}

/** The most specific nav link matching the path ("/instructor/labs" wins over "/instructor"). */
function current(path: string, href: string, links: { href: string }[]): boolean {
  const best = links.filter((l) => path === l.href || path.startsWith(`${l.href}/`)).sort((a, b) => b.href.length - a.href.length)[0];
  return best?.href === href;
}
