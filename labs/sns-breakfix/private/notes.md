A deleted subscription is the incident: topic and queue intact, but no delivery. Built from typed
`sns.*` break actions (create_topic, subscribe_sqs, unsubscribe_sqs) plus `sqs.create_queue`.

Baseline 20.00 = the leave-things-alone task. The delivery proof reuses the SQS message probe, so
grading is still a pure function of stored evidence (nothing is consumed; the probe waits ~5 s for an
asynchronous delivery).

Engine notes: delivery is in-sandbox only (no egress); no ARNs are graded.
