"""
Retrieval planners: turn a question into a validated retrieval plan.

A plan is a small dict and nothing else:

    {"metric": "<registry metric id>", "filters": {"<dim>": "<value>"}, "by": "<dim>" or None}

A planner only chooses. The KPI registry computes every number in SQL.

Two planners ship here:

  StubPlanner  deterministic keyword rules. The default. Offline, no credentials.
  LLMPlanner   asks a language model for the plan through a ModelClient.

Every plan from every planner goes through validate_plan() before any SQL
runs. The LLM planner also uses the validator to retry once: a bad plan is
sent back to the model with the errors. A second bad plan raises PlanError.
Nothing falls back to the stub.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

PLAN_KEYS = ("metric", "filters", "by")
UNANSWERABLE_KEY = "reason_if_unanswerable"


class PlanError(Exception):
    """The planner could not produce a valid plan."""


class UnanswerableQuestion(Exception):
    """The model said no registry metric answers the question."""


# ---------------------------------------------------------------------------
# Catalog: the only thing a model is shown besides the question.
# ---------------------------------------------------------------------------

def build_catalog(registry: dict) -> dict:
    """Metric ids, descriptions, units, allowed dimensions and their values.

    No SQL, no table names, no data rows.
    """
    metrics = {
        mid: {
            "label": m["label"],
            "description": m["description"],
            "unit": m["unit"],
            "dimensions": list(m.get("filters", {})),
        }
        for mid, m in registry["metrics"].items()
    }
    return {"metrics": metrics, "dimensions": registry.get("dimensions", {})}


# ---------------------------------------------------------------------------
# Validation: the contract every plan must meet before execution.
# ---------------------------------------------------------------------------

def _value_error(dim: str, value, spec: dict) -> str | None:
    if not isinstance(value, str):
        return f"filter '{dim}' must be a string, got {type(value).__name__}"
    if "values" in spec and value not in spec["values"]:
        return f"filter '{dim}' has value '{value}'; allowed: {', '.join(spec['values'])}"
    if "pattern" in spec and not re.fullmatch(spec["pattern"], value):
        return f"filter '{dim}' has value '{value}'; expected format {spec.get('description', spec['pattern'])}"
    # YYYY-MM strings sort correctly as text, so a plain comparison is enough.
    if "min" in spec and value < spec["min"]:
        return f"filter '{dim}' value '{value}' is before the first available {dim} ({spec['min']})"
    if "max" in spec and value > spec["max"]:
        return f"filter '{dim}' value '{value}' is after the last available {dim} ({spec['max']})"
    return None


def validate_plan(plan, registry: dict) -> list[str]:
    """Return a list of problems with the plan. An empty list means valid."""
    if not isinstance(plan, dict):
        return ["plan must be a JSON object"]

    errors = []
    extra = sorted(set(plan) - set(PLAN_KEYS))
    if extra:
        errors.append(f"unexpected keys: {', '.join(extra)}")

    metrics = registry["metrics"]
    dim_specs = registry.get("dimensions", {})

    metric_id = plan.get("metric")
    allowed_dims = None
    if not isinstance(metric_id, str) or not metric_id:
        errors.append("'metric' must be a metric id from the catalog")
    elif metric_id not in metrics:
        errors.append(f"unknown metric '{metric_id}'; allowed: {', '.join(metrics)}")
    else:
        allowed_dims = list(metrics[metric_id].get("filters", {}))

    filters = plan.get("filters", {})
    if not isinstance(filters, dict):
        errors.append("'filters' must be an object")
        filters = {}
    for dim, value in filters.items():
        if allowed_dims is not None and dim not in allowed_dims:
            errors.append(f"metric '{metric_id}' cannot be filtered by '{dim}'; "
                          f"allowed: {', '.join(allowed_dims) or '(none)'}")
            continue
        if dim not in dim_specs:
            errors.append(f"unknown dimension '{dim}'")
            continue
        err = _value_error(dim, value, dim_specs[dim])
        if err:
            errors.append(err)

    by = plan.get("by")
    if by is not None:
        if not isinstance(by, str):
            errors.append("'by' must be a dimension name or null")
        elif allowed_dims is not None and by not in allowed_dims:
            errors.append(f"metric '{metric_id}' cannot be broken down by '{by}'; "
                          f"allowed: {', '.join(allowed_dims) or '(none)'}")
        elif by not in dim_specs:
            errors.append(f"unknown dimension '{by}'")
    return errors


def require_valid(plan, registry: dict) -> dict:
    """Raise PlanError unless the plan is valid. Returns the plan."""
    errors = validate_plan(plan, registry)
    if errors:
        raise PlanError("invalid retrieval plan: " + "; ".join(errors))
    return plan


# ---------------------------------------------------------------------------
# Stub planner (default): deterministic keyword rules, no model.
# ---------------------------------------------------------------------------

CHANNEL_WORDS = {
    "paid search": "paid_search", "ppc": "paid_search", "google": "paid_search",
    "paid social": "paid_social", "social": "paid_social", "meta": "paid_social",
    "email": "email", "newsletter": "email",
    "organic": "organic_search", "seo": "organic_search",
    "referral": "referral", "word of mouth": "referral",
    "walk in": "walk_in", "walk-in": "walk_in", "walkin": "walk_in",
}
STORE_WORDS = {
    "riverside": "Riverside", "highland": "Highland Park",
    "oakmont": "Oakmont", "lakeside": "Lakeside",
}

# Ordered keyword -> metric rules. First match wins. More specific phrases are
# listed before the generic ones so "cost per sale" is not mistaken for "sales".
METRIC_RULES = [
    (("burdened", "fully loaded", "loaded cost", "true cost"), "burdened_cost_per_sale"),
    (("media cost", "cost per sale", "cac", "acquisition cost"), "media_cost_per_sale"),
    (("lead to sale", "conversion", "close rate", "win rate", "lead-to-sale"), "lead_to_sale_rate"),
    (("average ticket", "avg ticket", "average order", "ticket size"), "average_ticket"),
    (("gross margin", "margin"), "gross_margin"),
    (("how many", "count", "number of sales", "transactions", "sales volume"), "sales_count"),
    (("revenue", "sales", "top line", "turnover"), "total_revenue"),
]

SALE_TYPE_WORDS = {"service": r"\bservices?\b", "retail": r"\bretail\b"}

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}
# A month name only counts when a four-digit year follows it ("June 2025",
# "jun. 2025", "june, 2025"). A bare month name is ambiguous and is ignored.
_MONTH_NAME_YEAR = re.compile(r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) +
                              r")\.?,?\s+(20\d{2})\b")
_ISO_MONTH = re.compile(r"\b(20\d{2})-(0[1-9]|1[0-2])\b")
_YEAR = re.compile(r"\b20\d{2}\b")

# metrics sourced from the per-channel mart only support a channel breakdown
_MART_ONLY = {"media_cost_per_sale", "burdened_cost_per_sale", "lead_to_sale_rate"}


def parse_month(q: str) -> str | None:
    """'2025-06', 'June 2025' or 'jun 2025' -> '2025-06'. Anything else -> None."""
    m = _ISO_MONTH.search(q)
    if m:
        return m.group(0)
    m = _MONTH_NAME_YEAR.search(q.lower())
    if m:
        return f"{m.group(2)}-{MONTHS[m.group(1)]:02d}"
    return None


def stub_plan(question: str) -> tuple[dict, dict]:
    """Keyword stub: map a question to (plan, ignored) with fixed rules.

    `ignored` lists constraints the stub recognized in the question but could
    not put in the plan (a store, month or sale type on a channel-only metric,
    or a bare year), so the caller can say so instead of dropping them
    silently. Constraints the keyword rules do not recognize at all cannot be
    listed; that is the stub's real limit and why the LLM planner exists.

    It never says "unanswerable": an unmatched question gets total_revenue.
    """
    q = question.lower()

    metric = next((mid for keywords, mid in METRIC_RULES if any(k in q for k in keywords)),
                  "total_revenue")

    filters: dict[str, str] = {}
    ignored: dict[str, str] = {}
    for word, canonical in CHANNEL_WORDS.items():
        if word in q:
            filters["channel"] = canonical
            break
    for word, canonical in STORE_WORDS.items():
        if word in q:
            filters["store"] = canonical
            break
    # One sale type named is a filter; both named ("retail vs service") is a split.
    sale_types = [st for st, pat in SALE_TYPE_WORDS.items() if re.search(pat, q)]
    if len(sale_types) == 1:
        filters["sale_type"] = sale_types[0]
    month = parse_month(q)
    if month:
        filters["month"] = month
    else:
        year = _YEAR.search(q)
        if year:
            # The registry has months, not years, so a bare year cannot be a filter.
            ignored["year"] = year.group(0)

    by = None
    if "by channel" in q or "per channel" in q or "each channel" in q:
        by = "channel"
    elif "by store" in q or "per store" in q or "each store" in q or "by location" in q:
        by = "store"
    elif "by month" in q or "monthly" in q or "over time" in q:
        by = "month"
    elif "by sale type" in q or "by type" in q or len(sale_types) == 2:
        by = "sale_type"

    if metric in _MART_ONLY:
        for dim in ("store", "month", "sale_type"):
            if dim in filters:
                ignored[dim] = filters.pop(dim)
        if by in ("store", "month", "sale_type"):
            ignored["by"] = by
            by = "channel"

    return {"metric": metric, "filters": filters, "by": by}, ignored


def plan_from_question(question: str) -> dict:
    """Keyword stub: the plan only (see stub_plan for what it ignored)."""
    return stub_plan(question)[0]


class StubPlanner:
    name = "stub"

    def __init__(self):
        # constraints recognized but left out of the last plan (see stub_plan)
        self.ignored: dict[str, str] = {}

    def plan(self, question: str) -> dict:
        plan, self.ignored = stub_plan(question)
        return plan


# ---------------------------------------------------------------------------
# LLM planner: the provider seam plus the validate-and-retry loop.
# ---------------------------------------------------------------------------

class ModelClient(Protocol):
    """What a provider must implement. One method, text in, JSON text out.

    The client is handed a system prompt, a user prompt and a JSON schema the
    response must follow. It returns the raw response text. It does not parse,
    validate or execute anything; the planner does that.
    """

    name: str

    def generate_json(self, system: str, prompt: str, schema: dict) -> str: ...


SYSTEM_PROMPT = """\
You translate a business question into a retrieval plan for a KPI registry.
You choose; you never calculate. You do not see any data and you must not
state, estimate or compute any number.

Return one JSON object with exactly these keys:
  metric                  a metric id from the catalog, or null if no metric answers the question
  filters                 an object with every dimension as a key: its value if the question
                          states it, otherwise null
  by                      one dimension to break the metric down by, or null
  reason_if_unanswerable  null, or one short sentence when metric is null

Rules:
- Use only metric ids, dimensions and values that appear in the catalog.
- A metric may only be filtered or broken down by the dimensions listed for it.
- Every constraint the question states (a channel, a store, a sale type, a
  month) must appear as a filter. A month is written YYYY-MM, so "June 2025"
  is "2025-06". Never drop a stated constraint.
- If a stated constraint cannot be expressed with the chosen metric's
  dimensions (for example a store filter on a channel-only metric, or a
  whole year when only single months exist), the question is unanswerable.
- Do not add a filter the question does not ask for.
- Use "by" when the question asks to compare or split across a dimension
  ("by channel", "per store", "each month", "which store").
- If the question cannot be answered by any metric in the catalog, set metric
  to null, every filter to null, by to null, and say why in reason_if_unanswerable.
"""


def plan_schema(catalog: dict) -> dict:
    """JSON schema for the model's response, built from the catalog.

    The schema narrows the model to catalog ids and values. It cannot express
    which dimensions each metric allows, so validate_plan() still runs.

    Every filter slot is required and nullable. With optional slots the model
    sometimes left out a constraint the question stated ("in June 2025") and
    the plan still looked valid. Making it fill or null each slot fixed that
    in the live test. Nulls are dropped before validation.
    """
    dims = catalog["dimensions"]
    filter_props = {}
    for dim, spec in dims.items():
        prop = {"type": "string"}
        if "values" in spec:
            prop["enum"] = list(spec["values"])
        filter_props[dim] = {"anyOf": [prop, {"type": "null"}],
                             "description": spec.get("description", dim) + " Null if not stated."}
    return {
        "type": "object",
        "properties": {
            "metric": {"anyOf": [{"type": "string", "enum": list(catalog["metrics"])},
                                 {"type": "null"}]},
            "filters": {"type": "object", "properties": filter_props,
                        "required": list(dims), "additionalProperties": False},
            "by": {"anyOf": [{"type": "string", "enum": list(dims)}, {"type": "null"}]},
            UNANSWERABLE_KEY: {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["metric", "filters", "by", UNANSWERABLE_KEY],
        "additionalProperties": False,
    }


def build_prompt(question: str, catalog: dict) -> str:
    return ("Catalog:\n" + json.dumps(catalog, indent=2) +
            "\n\nQuestion: " + question.strip() + "\n")


def build_retry_prompt(question: str, catalog: dict, previous: str, errors: list[str]) -> str:
    return (build_prompt(question, catalog) +
            "\nYour previous answer was rejected by the validator.\n"
            "Previous answer:\n" + previous.strip() + "\n"
            "Problems:\n" + "\n".join(f"- {e}" for e in errors) +
            "\nReturn a corrected JSON object.\n")


class LLMPlanner:
    """Ask a model for a plan, validate it, retry once with the errors."""

    def __init__(self, client: ModelClient, registry: dict, max_attempts: int = 2):
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.client = client
        self.registry = registry
        self.max_attempts = max_attempts
        self.catalog = build_catalog(registry)
        self.schema = plan_schema(self.catalog)
        self.name = f"llm:{getattr(client, 'name', type(client).__name__)}"
        # (raw response, errors) for each attempt of the last plan() call.
        self.attempts: list[tuple[str, list[str]]] = []

    def _check(self, raw: str) -> tuple[dict | None, list[str]]:
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as e:
            return None, [f"response was not valid JSON ({e})"]
        if not isinstance(obj, dict):
            return None, ["response must be a JSON object"]

        reason = obj.pop(UNANSWERABLE_KEY, None)
        if obj.get("metric") is None:
            if isinstance(reason, str) and reason.strip():
                raise UnanswerableQuestion(reason.strip())
            return None, ["metric is null but reason_if_unanswerable is empty"]

        # Normalize: a missing or null filters object means no filters, and a
        # null filter value means "not filtered". Anything else is checked as-is.
        if obj.get("filters") is None:
            obj["filters"] = {}
        if isinstance(obj["filters"], dict):
            obj["filters"] = {k: v for k, v in obj["filters"].items() if v is not None}
        obj.setdefault("by", None)

        errors = validate_plan(obj, self.registry)
        return (obj, []) if not errors else (None, errors)

    def plan(self, question: str) -> dict:
        self.attempts = []
        prompt = build_prompt(question, self.catalog)
        for _ in range(self.max_attempts):
            raw = self.client.generate_json(SYSTEM_PROMPT, prompt, self.schema)
            try:
                plan, errors = self._check(raw)
            except UnanswerableQuestion:
                self.attempts.append((raw, []))
                raise
            self.attempts.append((raw, errors))
            if plan is not None:
                return plan
            prompt = build_retry_prompt(question, self.catalog, raw, errors)
        raise PlanError(f"model returned an invalid plan {self.max_attempts} times; "
                        f"last problems: {'; '.join(self.attempts[-1][1])}")
