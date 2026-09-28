Teaches fan-out: topic + queue + subscription + publish, with delivery proven by the SQS message probe.

Engine notes: delivery is in-sandbox SNS→SQS only (no egress). The peek probe waits up to ~5 s for a
delivery to land, so an asynchronous publish is not flaky. No ARNs are graded.
