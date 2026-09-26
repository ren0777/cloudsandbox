from typing import Any

from pydantic import ValidationError

from .v1 import LabV1

SCHEMAS: dict[int, type[LabV1]] = {1: LabV1}
LabDefinition = LabV1  # union of all schema models as more versions are added


class LabValidationError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def parse_definition(data: Any) -> LabDefinition:
    if not isinstance(data, dict):
        raise LabValidationError(["lab.yaml must be a mapping"])
    sv = data.get("schema_version")
    model = SCHEMAS.get(sv) if isinstance(sv, int) else None
    if model is None:
        raise LabValidationError([f"unsupported schema_version {sv!r} (known: {sorted(SCHEMAS)})"])
    try:
        return model.model_validate(data)
    except ValidationError as e:
        raise LabValidationError([f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()]) from e
