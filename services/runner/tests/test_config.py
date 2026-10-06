"""RUNNER_SECRET validation (maintenance M2): the runner refuses to boot with a known dev default,
a value containing "change-me", or anything shorter than 32 characters."""
import pytest
from pydantic import ValidationError

from app.config import KNOWN_INSECURE_SECRETS, MIN_SECRET_LENGTH, Settings, is_insecure_secret

SECURE = "7c2f9a1e5b3d8064a4c8e2f7b9d1a3c5"  # 32 chars, not a known default


def test_accepts_long_unique_secret():
    assert Settings(secret=SECURE).secret == SECURE


def test_exactly_min_length_is_accepted():
    assert Settings(secret="b" * MIN_SECRET_LENGTH).secret == "b" * MIN_SECRET_LENGTH


@pytest.mark.parametrize("bad", sorted(KNOWN_INSECURE_SECRETS))
def test_refuses_every_known_dev_default(bad):
    with pytest.raises(ValidationError):
        Settings(secret=bad)


def test_refuses_short_and_change_me():
    with pytest.raises(ValidationError):
        Settings(secret="a" * (MIN_SECRET_LENGTH - 1))
    with pytest.raises(ValidationError):
        Settings(secret="runner-secret-change-me-0123456789abcdef")


def test_error_names_the_variable():
    with pytest.raises(ValidationError) as e:
        Settings(secret="x" * 20)
    assert "RUNNER_SECRET" in str(e.value)


def test_is_insecure_secret_covers_the_three_rules():
    assert is_insecure_secret("change-me")
    assert is_insecure_secret("short")
    assert is_insecure_secret("dev-runner-m45-secret")
    assert not is_insecure_secret(SECURE)
