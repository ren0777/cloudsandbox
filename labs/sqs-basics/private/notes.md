Teaches the decoupling pattern: create a queue, set a real retention policy, put a message on it.

Engine notes: the message check is a **probe** — evidence capture peeks up to 10 messages with
`VisibilityTimeout=0` (nothing is consumed), so grading is deterministic and the student's message stays
on the queue for the CLI. FIFO queues are supported by the engine contract; this lab uses Standard.
