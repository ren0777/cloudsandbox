# Instructor notes — s3-basics (PRIVATE)
- The hidden check on task 3 requires `Content-Type: text/html`. `aws s3 cp` and browser uploads of
  `.html` files set it automatically; `--content-type text/plain` or uploading a `.txt` renamed
  fails it.
