"""Namespaces reserved for later phases. They exist so lab authors get a precise error ("not available
yet") instead of "unknown check", and so the registry layout matches the full architecture."""

from ..registry import stub

_LATER = "planned for a later phase (not in vertical slice 1)"


for t in ("audit.called", "audit.order"):
    stub(t, "the API audit proxy is not built in slice 1 (NullAuditSource)", collector="audit")
