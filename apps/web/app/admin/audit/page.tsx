"use client";
import { AuditLog } from "@/components/audit-log";
import { Shell } from "@/components/shell";

export default function AdminAudit() {
  return (
    <Shell>
      <div className="stack" style={{ gap: 18 }}>
        <div><div className="eyebrow">Admin</div><h1>Audit log</h1>
          <p className="small muted" style={{ margin: "6px 0 0" }}>Every instructor and admin action, newest first. Entries can&apos;t be edited or deleted.</p></div>
        <AuditLog base="/api/admin/audit" />
      </div>
    </Shell>
  );
}
