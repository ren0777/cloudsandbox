A settings incident: the queue exists, but visibility timeout (12 h) and delivery delay (15 min) make it
look like messages disappear. The starting state is one typed `sqs.create_queue` break action.

Baseline 20.00 = the leave-the-queue-alone task. Grading reads the queue attributes from evidence; the
hidden retention check stops a lazy "delete and recreate".

Engine notes: all four SQS operations used here are contract-verified on Floci and Moto.
