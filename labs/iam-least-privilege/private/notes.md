# Instructor notes - iam-least-privilege (PRIVATE)
- Grading uses the CloudLabs policy evaluator (identity policies: user + its groups). Conditions are
  not evaluated. The hidden check makes sure s3:DeleteObject is denied.
- Common mistake: attaching AmazonS3ReadOnlyAccess. It passes read but also allows reading every
  bucket, so the payroll check fails.
