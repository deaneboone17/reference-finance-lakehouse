"""
Offline tests for the plan validator, the stub planner and the LLM planner.

No network, no credentials, no warehouse. The LLM planner is driven by a fake
model client that returns canned responses and records what it was sent.
"""

import contextlib
import io
import json
import os
import unittest
from unittest import mock

import yaml

from ai_query import ask
from ai_query.planner import (
    LLMPlanner, PlanError, StubPlanner, UnanswerableQuestion,
    build_catalog, plan_from_question, plan_schema, validate_plan,
)
from registry import query

REGISTRY = query.load_registry()
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeClient:
    """Returns canned responses in order and records every call."""

    name = "fake"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def generate_json(self, system, prompt, schema):
        self.calls.append({"system": system, "prompt": prompt, "schema": schema})
        if not self.responses:
            raise AssertionError("fake client called more times than expected")
        r = self.responses.pop(0)
        return r if isinstance(r, str) else json.dumps(r)


def reply(metric, filters=None, by=None, reason=None):
    return {"metric": metric, "filters": filters or {}, "by": by, "reason_if_unanswerable": reason}


class ValidatorTests(unittest.TestCase):

    def assertValid(self, plan):
        self.assertEqual(validate_plan(plan, REGISTRY), [])

    def assertInvalid(self, plan, fragment):
        errors = validate_plan(plan, REGISTRY)
        self.assertTrue(errors, f"expected an error for {plan}")
        self.assertIn(fragment, " | ".join(errors))

    def test_good_plans(self):
        self.assertValid({"metric": "total_revenue", "filters": {}, "by": None})
        self.assertValid({"metric": "total_revenue", "filters": {"channel": "paid_search"}, "by": "store"})
        self.assertValid({"metric": "average_ticket", "filters": {"month": "2025-06", "store": "Oakmont"}, "by": None})
        self.assertValid({"metric": "burdened_cost_per_sale", "filters": {}, "by": "channel"})

    def test_unknown_metric(self):
        self.assertInvalid({"metric": "net_profit", "filters": {}, "by": None}, "unknown metric 'net_profit'")

    def test_missing_metric(self):
        self.assertInvalid({"filters": {}, "by": None}, "'metric' must be")

    def test_filter_not_allowed_for_metric(self):
        self.assertInvalid({"metric": "burdened_cost_per_sale", "filters": {"store": "Oakmont"}, "by": None},
                           "cannot be filtered by 'store'")

    def test_bad_filter_value(self):
        self.assertInvalid({"metric": "total_revenue", "filters": {"channel": "tiktok"}, "by": None},
                           "filter 'channel' has value 'tiktok'")

    def test_non_string_filter_value(self):
        self.assertInvalid({"metric": "total_revenue", "filters": {"month": 202506}, "by": None},
                           "must be a string")

    def test_month_format_and_range(self):
        self.assertInvalid({"metric": "total_revenue", "filters": {"month": "June 2025"}, "by": None},
                           "expected format")
        self.assertInvalid({"metric": "total_revenue", "filters": {"month": "2026-01"}, "by": None},
                           "after the last available month")
        self.assertInvalid({"metric": "total_revenue", "filters": {"month": "2023-12"}, "by": None},
                           "before the first available month")

    def test_bad_dim(self):
        self.assertInvalid({"metric": "total_revenue", "filters": {}, "by": "region"}, "cannot be broken down by 'region'")

    def test_dim_not_allowed_for_metric(self):
        self.assertInvalid({"metric": "lead_to_sale_rate", "filters": {}, "by": "store"}, "cannot be broken down by 'store'")

    def test_extra_keys_rejected(self):
        # A plan cannot smuggle in a number or SQL.
        self.assertInvalid({"metric": "total_revenue", "filters": {}, "by": None, "value": 123.0}, "unexpected keys: value")

    def test_not_an_object(self):
        self.assertEqual(validate_plan(["total_revenue"], REGISTRY), ["plan must be a JSON object"])


class StubPlannerTests(unittest.TestCase):

    def test_run_sh_questions(self):
        self.assertEqual(plan_from_question("show me burdened cost per sale by channel"),
                         {"metric": "burdened_cost_per_sale", "filters": {}, "by": "channel"})
        self.assertEqual(plan_from_question("what was total revenue from paid search"),
                         {"metric": "total_revenue", "filters": {"channel": "paid_search"}, "by": None})

    def test_stub_plans_always_validate(self):
        questions = [
            "average ticket at riverside in 2025-06", "gross margin by store", "how many sales by month",
            "close rate for referral", "media cost per sale at oakmont by store", "what is the weather",
        ]
        for q in questions:
            with self.subTest(q=q):
                self.assertEqual(validate_plan(StubPlanner().plan(q), REGISTRY), [])


class LLMPlannerTests(unittest.TestCase):

    def test_good_plan_first_try(self):
        client = FakeClient(reply("total_revenue", {"channel": "email"}, "store"))
        plan = LLMPlanner(client, REGISTRY).plan("email revenue by store")
        self.assertEqual(plan, {"metric": "total_revenue", "filters": {"channel": "email"}, "by": "store"})
        self.assertEqual(len(client.calls), 1)

    def test_retry_then_success_sends_errors_back(self):
        client = FakeClient(reply("burdened_cost_per_sale", {"store": "Oakmont"}),
                            reply("burdened_cost_per_sale", {}, "channel"))
        planner = LLMPlanner(client, REGISTRY)
        plan = planner.plan("burdened cost at oakmont")
        self.assertEqual(plan["by"], "channel")
        self.assertEqual(len(client.calls), 2)
        self.assertIn("rejected by the validator", client.calls[1]["prompt"])
        self.assertIn("cannot be filtered by 'store'", client.calls[1]["prompt"])
        self.assertEqual(len(planner.attempts), 2)

    def test_retry_then_fail_loudly(self):
        client = FakeClient(reply("net_profit"), reply("net_profit"))
        with self.assertRaises(PlanError) as ctx:
            LLMPlanner(client, REGISTRY).plan("net profit?")
        self.assertIn("unknown metric 'net_profit'", str(ctx.exception))
        self.assertEqual(len(client.calls), 2)

    def test_invalid_json_is_retried(self):
        client = FakeClient("not json", reply("sales_count"))
        plan = LLMPlanner(client, REGISTRY).plan("how many sales")
        self.assertEqual(plan["metric"], "sales_count")
        self.assertIn("not valid JSON", client.calls[1]["prompt"])

    def test_unanswerable_fails_without_retry(self):
        client = FakeClient(reply(None, reason="The catalog has no headcount metric."))
        with self.assertRaises(UnanswerableQuestion) as ctx:
            LLMPlanner(client, REGISTRY).plan("how many employees do we have")
        self.assertIn("headcount", str(ctx.exception))
        self.assertEqual(len(client.calls), 1)

    def test_null_metric_without_reason_is_a_bad_plan(self):
        client = FakeClient(reply(None), reply(None))
        with self.assertRaises(PlanError):
            LLMPlanner(client, REGISTRY).plan("??")
        self.assertEqual(len(client.calls), 2)

    def test_null_filter_values_mean_unfiltered(self):
        client = FakeClient(reply("gross_margin", {"channel": None, "store": "Lakeside"}))
        plan = LLMPlanner(client, REGISTRY).plan("gross margin at lakeside")
        self.assertEqual(plan["filters"], {"store": "Lakeside"})

    def test_model_sees_catalog_only(self):
        client = FakeClient(reply("total_revenue"))
        LLMPlanner(client, REGISTRY).plan("revenue")
        sent = client.calls[0]["system"] + client.calls[0]["prompt"]
        self.assertNotIn("select", sent.lower())
        self.assertNotIn("gold.", sent)
        for mid in REGISTRY["metrics"]:
            self.assertIn(mid, sent)

    def test_schema_matches_registry(self):
        schema = plan_schema(build_catalog(REGISTRY))
        metric_enum = schema["properties"]["metric"]["anyOf"][0]["enum"]
        self.assertEqual(set(metric_enum), set(REGISTRY["metrics"]))
        filters = schema["properties"]["filters"]
        channel = filters["properties"]["channel"]["anyOf"][0]["enum"]
        self.assertEqual(channel, REGISTRY["dimensions"]["channel"]["values"])
        # every filter slot must be filled or nulled, so a stated constraint cannot be skipped
        self.assertEqual(set(filters["required"]), set(REGISTRY["dimensions"]))


class AskTests(unittest.TestCase):

    def test_invalid_plan_never_reaches_sql(self):
        class BadPlanner:
            name = "bad"

            def plan(self, question):
                return {"metric": "total_revenue", "filters": {"channel": "tiktok"}, "by": None}

        with mock.patch.object(query, "run_metric", side_effect=AssertionError("SQL ran")):
            with self.assertRaises(PlanError):
                ask.answer("tiktok revenue", BadPlanner(), REGISTRY)

    def _run_main(self, client, question):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(ask, "make_planner", return_value=LLMPlanner(client, REGISTRY)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ask.main(["--planner", "vertex", question])
        return code, out.getvalue(), err.getvalue()

    def test_cli_unanswerable_exits_3(self):
        code, out, err = self._run_main(FakeClient(reply(None, reason="No headcount metric.")), "headcount?")
        self.assertEqual(code, 3)
        self.assertIn("Not answerable", err)
        self.assertEqual(out, "")

    def test_cli_invalid_plan_exits_2_without_fallback(self):
        with mock.patch.object(query, "run_metric", side_effect=AssertionError("SQL ran")):
            code, out, err = self._run_main(FakeClient(reply("net_profit"), reply("net_profit")), "net profit?")
        self.assertEqual(code, 2)
        self.assertIn("No valid retrieval plan", err)
        self.assertEqual(out, "")

    def test_vertex_without_project_exits_2(self):
        env = {k: v for k, v in os.environ.items() if k != "GOOGLE_CLOUD_PROJECT"}
        err = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stderr(err):
            code = ask.main(["--planner", "vertex", "total revenue"])
        self.assertEqual(code, 2)
        self.assertIn("not configured", err.getvalue())


class RegistryConsistencyTests(unittest.TestCase):

    def test_registry_values_match_gold_tests(self):
        """The registry's allowed values and the dbt accepted_values tests agree."""
        with open(os.path.join(ROOT, "models", "gold", "_gold.yml")) as f:
            gold = yaml.safe_load(f)
        fct = next(m for m in gold["models"] if m["name"] == "fct_sales")
        accepted = {}
        for col in fct["columns"]:
            for t in col.get("data_tests", []):
                if isinstance(t, dict) and "accepted_values" in t:
                    accepted[col["name"]] = set(t["accepted_values"]["arguments"]["values"])
        dims = REGISTRY["dimensions"]
        self.assertEqual(set(dims["store"]["values"]), accepted["store_name"])
        self.assertEqual(set(dims["sale_type"]["values"]), accepted["sale_type"])
        # gold also accepts 'unknown' for unmapped channels; the registry does not offer it.
        self.assertEqual(set(dims["channel"]["values"]), accepted["channel"] - {"unknown"})


if __name__ == "__main__":
    unittest.main()
