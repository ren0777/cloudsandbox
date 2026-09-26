# Instructor notes - lambda-basics (PRIVATE)
- Pinned to the MiniStack engine: it is the only CloudLabs engine that executes Lambda code without
  giving the sandbox Docker access (see docs/EMULATOR-EVALUATION.md).
- Task 3 is graded by invoking the function during evidence capture (a check *probe*) with the example
  order and, as a hidden check, an empty order (`{"items": []}` must return total 0).
- Common mistakes: forgetting **Deploy** after editing, hard-coding 0.08 (still passes; discuss it),
  returning the total as a string, or returning an API Gateway style `{"statusCode", "body"}` object.
