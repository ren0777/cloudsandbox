# Author notes (PRIVATE).

Grading uses three probes, run in this order during evidence capture:

1. `lambda.invoke_returns` invokes the function with a hand-built SQS event (one good order, one record
   whose body is `not json`) and expects exactly `msg-2` in `batchItemFailures`. The good order (3001) is
   then checked in the table (hidden).
2. `sqs.delivers_item` removes order 9001 from the table, sends it to the queue and waits up to 20 s for
   the trigger to write it back. Removing it first means an item left by an earlier attempt can't pass.
3. The DynamoDB collector scans the table afterwards.

The partial script builds everything except the trigger, so the last two tasks fail (70).
