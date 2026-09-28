The broken state is built entirely from typed `vpc.*` break actions (no shell): the network is created
without the 0.0.0.0/0 route and with SSH-only ingress, which is the missing-route/missing-port incident.
The create-then-delete variants (`vpc.delete_route`, `vpc.revoke_ingress`) exist in the catalogue and are
unit-tested; this setup omits them because the same broken state is reached with ~half the AWS CLI calls,
and a CLI-heavy setup must stay well inside the runner's job cap.

Grading rewards the repair (route + HTTP) and protects the remaining network (VPC/subnet/SSH rule), with a
hidden check that SSH was not opened to the world. Baseline 25.00 = the intact-network task.

Engine notes: configuration-only network; `vpc.create_route` and `vpc.authorize_ingress` are supported on
Floci and Moto (verified by the M44 contract suite).
