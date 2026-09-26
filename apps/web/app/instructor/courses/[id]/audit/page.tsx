"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AuditLog } from "@/components/audit-log";
import { Shell } from "@/components/shell";

export default function CourseAudit() {
  const { id } = useParams<{ id: string }>();
  return (
    <Shell>
      <div className="stack" style={{ gap: 18 }}>
        <Link href={`/instructor/courses/${id}`} className="small">← Course</Link>
        <div><div className="eyebrow">Course</div><h1>Activity log</h1>
          <p className="small muted" style={{ margin: "6px 0 0" }}>Roster, assignment, extension, regrade and session actions in this course.</p></div>
        <AuditLog base={`/api/instructor/courses/${id}/audit`} showCourse={false} />
      </div>
    </Shell>
  );
}
