# Instructor notes - iam-breakfix (PRIVATE)
- Break-fix: `public/setup.sh` creates the broken state per student (again on Reset). The untouched environment
  scores 0: the admin policy is attached, the intern is in the group, and the barista can delete the table.
- Common mistakes: deleting the whole group (fails "keep working"), attaching the orders policy to the user
  instead of the group (fails the attachment check), removing the intern from the group but leaving their inline
  `*` policy (still has access, fails offboarding), writing a new broad policy (fails the hidden least-privilege
  check).
- Discussion: why "make everyone admin" is tempting, and how the Policy simulator proves least privilege.
