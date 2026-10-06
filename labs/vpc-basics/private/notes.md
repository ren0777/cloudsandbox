Guide the student to the public-subnet pattern: VPC → subnet (public) → internet gateway attached →
route 0.0.0.0/0 to the gateway → associate the route table → security group with HTTP.

Engine notes: the network is configuration-only in every engine (no real traffic). Floci cascades
`delete-vpc` to dependent subnets; no check depends on dependency errors. Resources are matched by
`Name` tag, so names must be set exactly as the lab shows them.
