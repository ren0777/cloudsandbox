# Mission 16 — instructor notes (PRIVATE)

**What it teaches:** S3 assigns version IDs only once Bucket Versioning is enabled; an object written earlier
keeps version ID `null`. The partial solution reaches a perfect end state in the wrong order and scores 70:
only the audit checks (`audit.order`, `audit.called`) can see the difference.

**How it is graded:** the sandbox runs an API-audit proxy (the lab has `audit.*` checks). Calls from the terminal
count as `cli`, calls from the console as `console`. Setup and grading reads are never recorded. A student who
uploaded too early recovers by uploading again after enabling versioning, which is also the right fix in AWS.

**Discussion:** in AWS the same record comes from CloudTrail data events. Ask what else the log could prove
(who deleted an object, whether the console or a script made a change).
