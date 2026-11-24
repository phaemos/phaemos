"""
One rule for every PATCH: a field left out is kept, `null` clears a field named in `clearable` and is a 422 on any other.

    changed = apply_patch(device, payload, clearable={"owner_id"})
    db.commit()

`payload` is a Pydantic model (only the fields the client sent count) or a dict. The function sets the values on the model,
returns the names of the fields that changed and raises a 422 `validation_failed` for a `null` on a field that cannot be
cleared. It does not commit.
"""

from collections.abc import Iterable, Mapping

from app.errors import ApiError, Code


def apply_patch(model, payload, clearable: Iterable[str] = frozenset()) -> list[str]:
    if hasattr(payload, "model_dump"):
        sent = payload.model_dump(exclude_unset=True)
    elif isinstance(payload, Mapping):
        sent = dict(payload)
    else:
        raise TypeError("payload must be a Pydantic model or a dict")
    allowed_null = set(clearable)
    refused = sorted(name for name, value in sent.items() if value is None and name not in allowed_null)
    if refused:
        raise ApiError(
            422, Code.VALIDATION_FAILED,
            f"{', '.join(refused)} cannot be cleared. Leave it out to keep it",
            errors=[{"loc": ["body", name], "msg": "This field cannot be null", "type": "null_not_allowed"} for name in refused],
        )
    changed = []
    for name, value in sent.items():
        if getattr(model, name, None) != value:
            changed.append(name)
        setattr(model, name, value)
    return changed
