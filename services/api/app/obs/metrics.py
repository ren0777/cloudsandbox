from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

registry = CollectorRegistry()

sessions_active = Gauge("sessions_active", "Sessions in an active state", registry=registry)
provision_seconds = Histogram("provision_seconds", "Sandbox provisioning duration", registry=registry,
                              buckets=(1, 2, 5, 10, 20, 30, 60, 120, 180))
grading_seconds = Histogram("grading_seconds", "Evidence capture + grading duration",
                            registry=registry, buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 30))
session_failures_total = Counter("session_failures_total", "Sessions that ended FAILED",
                                 ["reason"], registry=registry)
capacity_rejections_total = Counter("capacity_rejections_total", "Start rejected: capacity full",
                                    registry=registry)
