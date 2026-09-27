"use client";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type { Me } from "@/lib/types";

type Ctx = { me: Me | null; loading: boolean; reload: () => Promise<void>; logout: () => Promise<void> };
const AuthCtx = createContext<Ctx>({ me: null, loading: true, reload: async () => {}, logout: async () => {} });

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const path = usePathname();

  const reload = useCallback(async () => {
    try {
      setMe(await api<Me>("/api/auth/me"));
    } catch (e) {
      if (!(e instanceof ApiError) || e.status !== 401) console.error(e);
      setMe(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => {
    // The public marketing site ("/") and the login page are reachable without an account.
    const isPublic = path === "/" || path === "/login";
    if (!loading && !me && !isPublic) router.replace(`/login?next=${encodeURIComponent(path)}`);
    // Roster-created accounts must replace their temporary password before anything else.
    if (!loading && me?.must_change_password && path !== "/account/password") router.replace("/account/password");
  }, [loading, me, path, router]);

  const logout = useCallback(async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    setMe(null);
    router.replace("/login");
  }, [router]);

  return <AuthCtx.Provider value={{ me, loading, reload, logout }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);

export function homeFor(me: Me): string {
  return me.role === "student" ? "/labs" : me.role === "instructor" ? "/instructor" : "/admin/status";
}
