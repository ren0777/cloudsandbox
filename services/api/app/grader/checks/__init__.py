_loaded = False


def load_all() -> None:
    global _loaded
    if _loaded:
        return
    from . import dynamodb, ec2, iam, lambda_, s3, stubs  # noqa: F401  (register checks)
    _loaded = True
