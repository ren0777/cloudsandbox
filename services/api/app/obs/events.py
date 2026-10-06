"""The fixed set of structured-log event names (PLAN §14). Logging any other name raises in tests."""

EVENTS: frozenset[str] = frozenset({
    "session.created",
    "session.transition",
    "sandbox.create.started", "sandbox.create.succeeded", "sandbox.create.failed",
    "sandbox.destroy.started", "sandbox.destroy.succeeded", "sandbox.destroy.failed",
    "terminal.ticket.issued", "terminal.ticket.rejected",
    "terminal.connected", "terminal.closed",
    "grader.progress",
    "grader.submit.started", "grader.submit.finished", "grader.submit.failed",
    "evidence.stored",
    "grade.regraded",
    "reconciler.action",
    "janitor.orphan_removed",
    "runner.unavailable",
    "capacity.rejected",
    "authz.denied",
    # Amendments recorded in STATUS.md decision D3:
    "assignment.override.granted",
    "http.request.failed",
    "background.task.failed",
    # Phase 5 (STATUS D15): every instructor/admin action is also an audit_events row.
    "audit.recorded",
    # Phase 6 (STATUS D21): badges earned from verified attempts.
    "badge.awarded",
    # Phase 9 (STATUS D43): instructor preview sandboxes (M42).
    "preview.started", "preview.reset", "preview.stopped", "preview.destroy.failed",
})
