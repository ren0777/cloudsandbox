"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { homeFor, useAuth } from "@/components/auth";

export default function Home() {
  const { me, loading } = useAuth();
  const router = useRouter();
  useEffect(() => { if (!loading && me) router.replace(homeFor(me)); }, [me, loading, router]);
  return <div className="page muted"><span className="spinner" /> Loading…</div>;
}
