_loaded = False


def load_all() -> None:
    global _loaded
    if _loaded:
        return
    from . import audit, dynamodb, ec2, iam, lambda_, s3, sns, sqs, vpc  # noqa: F401  (register checks)
    _loaded = True
