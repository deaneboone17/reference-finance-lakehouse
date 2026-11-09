"""
Offline tests for the registry CLI (registry/query.py). No warehouse needed:
every case here fails or formats before any SQL runs.
"""

import contextlib
import io
import unittest
from decimal import Decimal

from registry import query


class FormatValueTests(unittest.TestCase):

    def test_decimal_and_float_get_separators(self):
        self.assertEqual(query.format_value(Decimal("1362448.40")), "1,362,448.40")
        self.assertEqual(query.format_value(125.67), "125.67")
        self.assertEqual(query.format_value(1175776.333), "1,175,776.33")

    def test_ints_and_none(self):
        self.assertEqual(query.format_value(9268), "9,268")
        self.assertEqual(query.format_value(None), "None")


class CliErrorTests(unittest.TestCase):

    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = query.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_bad_by_exits_2_with_a_clear_message(self):
        code, out, err = self._run("burdened_cost_per_sale", "--by", "store")
        self.assertEqual(code, 2)
        self.assertIn("cannot be broken down by 'store'", err)
        self.assertIn("Allowed: channel", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(out, "")

    def test_bad_filter_dimension_exits_2(self):
        code, _, err = self._run("lead_to_sale_rate", "--filter", "month=2025-06")
        self.assertEqual(code, 2)
        self.assertIn("no filterable dimension 'month'", err)

    def test_unknown_metric_exits_2(self):
        code, _, err = self._run("net_profit")
        self.assertEqual(code, 2)
        self.assertIn("unknown metric 'net_profit'", err)

    def test_unsafe_filter_value_exits_2(self):
        code, _, err = self._run("total_revenue", "--filter", "channel=x'; drop table t;--")
        self.assertEqual(code, 2)
        self.assertIn("unsafe filter value", err)


if __name__ == "__main__":
    unittest.main()
