"""Secret validation (maintenance M2): a non-demo API must refuse to boot with a known dev default,
a value containing "change-me", or anything shorter than 32 characters."""
import pytest
from pydantic import ValidationError

from app.config import KNOWN_INSECURE_SECRETS, MIN_SECRET_LENGTH, Settings, is_insecure_secret

SECURE = "f3a9c2e1b7d4086a5c1e9f2b3d4a6c8e"  # 32 chars, not a known default
SECURE_RUNNER = "9b1d7f3a5c2e8046b6a1d9f4c7e2b8a0"


def _settings(**kw) -> Settings:
    base = dict(demo_mode=False, secret_key=SECURE, runner_secret=SECURE_RUNNER)
    base.update(kw)
    return Settings(**base)


def test_demo_mode_allows_the_shipped_dev_defaults():
    s = Settings(demo_mode=True, secret_key="dev-only-secret-change-me-0123456789abcdef",
                 runner_secret="dev-runner-secret-change-me")
    assert s.secret_key.endswith("abcdef")


@pytest.mark.parametrize("bad", sorted(KNOWN_INSECURE_SECRETS))
def test_production_refuses_every_known_dev_default(bad):
    with pytest.raises(ValidationError):
        _settings(secret_key=bad)


def test_production_refuses_change_me_inside_a_long_value():
    with pytest.raises(ValidationError) as e:
        _settings(secret_key="prod-secret-change-me-0123456789abcdef")
    assert "CL_SECRET_KEY" in str(e.value)


def test_production_refuses_short_secrets():
    with pytest.raises(ValidationError):
        _settings(secret_key="a" * (MIN_SECRET_LENGTH - 1))
    # exactly 32 is the boundary and must pass
    assert _settings(secret_key="a" * MIN_SECRET_LENGTH).secret_key == "a" * MIN_SECRET_LENGTH


def test_production_validates_runner_secret_too():
    with pytest.raises(ValidationError) as e:
        _settings(runner_secret="dev-runner-secret")
    assert "CL_RUNNER_SECRET" in str(e.value)


def test_accepts_long_unique_secrets():
    s = _settings()
    assert s.secret_key == SECURE and s.runner_secret == SECURE_RUNNER


def test_is_insecure_secret_covers_the_three_rules():
    assert is_insecure_secret("change-me")
    assert is_insecure_secret("short")
    assert is_insecure_secret("dev-insecure-change-me-dev-insecure-change-me")
    assert not is_insecure_secret(SECURE)
