"""
Rule metrics - the readings an alert rule may watch, in one place.

A rule is evaluated against the reading a post carries (and the score the model gave it). A rule on anything else (a health field,
the node type, a misspelt name) could never fire and would sit in the list looking as if it protected the machine. The rule routes
refuse such a metric with 422 and GET /api/v1/alert-metrics gives the dashboard this same list, so the rule form and the
backend cannot drift apart.
"""

from app.schemas.telemetry import HEALTH_FIELDS, TelemetryIngest

# not readings: who sent the post and the node's own health fields, which never reach a rule
_NOT_READINGS = HEALTH_FIELDS | {"device_id", "node_type"}
# the flags a rule may compare with 1 (true) or 0 (false)
BOOLEAN_METRICS = frozenset(
    name for name, field in TelemetryIngest.model_fields.items()
    if name not in _NOT_READINGS and "bool" in str(field.annotation)
)
# every reading field of a post and the anomaly score, which is fed into what the rules see
RULE_METRICS: tuple[str, ...] = tuple(
    sorted(name for name in TelemetryIngest.model_fields if name not in _NOT_READINGS)
) + ("anomaly_score",)
# a number must hold this long without a break before its alert is raised, unless the rule says otherwise. An on-or-off
# reading (gas, water, clipping) raises at once
DEFAULT_FOR_SECONDS = 30
# the part of the threshold a number must come back inside by before the alert can resolve
DEFAULT_CLEAR_MARGIN_SHARE = 0.02
CONDITIONS = ("gt", "lt", "eq")
SEVERITIES = ("info", "warning", "critical")


def default_for_seconds(metric: str) -> int:
    """30 seconds for a number and 0 for an on-or-off reading, which raises at once."""
    return 0 if metric in BOOLEAN_METRICS else DEFAULT_FOR_SECONDS


def default_clear_margin(threshold: float) -> float:
    """2 per cent of the threshold and never less than one unit of the threshold's last decimal place."""
    text = repr(float(threshold))
    decimals = max(1, len(text.split(".")[1].rstrip("0"))) if "." in text and "e" not in text else 1
    return max(DEFAULT_CLEAR_MARGIN_SHARE * abs(threshold), 10 ** -decimals)


def describe() -> dict:
    """The lists as the API returns them."""
    return {
        "metrics": [
            {"key": name, "type": "boolean" if name in BOOLEAN_METRICS else "number"} for name in RULE_METRICS
        ],
        "conditions": list(CONDITIONS),
        "severities": list(SEVERITIES),
    }
