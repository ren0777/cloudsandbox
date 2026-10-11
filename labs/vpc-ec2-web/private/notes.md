# Author notes (PRIVATE).

The partial run is the mistake this lab is about: a correct network, but the instance launched without
`--subnet-id`, so it runs in the default VPC (and without the security group). `ec2.instance_network` names
the VPC the instance is really in. Public IPs are not graded: Moto assigns one to every instance and Floci
none, so the public subnet is graded through `vpc.subnet public: true` instead.
