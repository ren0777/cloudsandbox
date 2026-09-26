"""Run Alembic migrations with the OWNER role (the app role can't alter schema)."""

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config


def config() -> Config:
    root = Path(__file__).resolve().parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    return cfg


def upgrade(revision: str = "head") -> None:
    command.upgrade(config(), revision)


if __name__ == "__main__":
    upgrade(sys.argv[1] if len(sys.argv) > 1 else "head")
