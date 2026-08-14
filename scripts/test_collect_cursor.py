#!/usr/bin/env python3
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from collect_cursor import build_cookie, compact_summary, extract_user_id, plan_is_usable


class CookieTests(unittest.TestCase):
    def test_extract_user_id_from_prefixed_token(self):
        self.assertEqual(extract_user_id("user_ABC123::jwt.here"), "user_ABC123")

    def test_build_cookie_encodes_separator(self):
        self.assertEqual(
            build_cookie("user_ABC::tok", "user_ABC"),
            "user_ABC%3A%3Atok",
        )

    def test_build_cookie_prefixes_bare_jwt(self):
        self.assertEqual(
            build_cookie("rawjwt", "user_ABC"),
            "user_ABC%3A%3Arawjwt",
        )


class SummaryTests(unittest.TestCase):
    def test_compact_summary_keeps_plan_numbers(self):
        snap = compact_summary(
            {
                "membershipType": "pro_plus",
                "limitType": "user",
                "billingCycleStart": "2026-08-13T00:00:00.000Z",
                "billingCycleEnd": "2026-09-13T00:00:00.000Z",
                "individualUsage": {
                    "plan": {"enabled": True, "used": 10, "limit": 100, "remaining": 90},
                    "onDemand": {"enabled": False, "used": 0},
                },
            },
            "user_ABC",
        )
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["plan"]["used"], 10)
        self.assertEqual(snap["plan"]["limit"], 100)
        self.assertNotIn("bonusTooltip", snap)
        self.assertNotIn("autoModelSelectedDisplayMessage", snap)

    def test_empty_plan_is_not_usable(self):
        snap = compact_summary({"individualUsage": {}}, "user_ABC")
        self.assertIsNone(snap["plan"])
        self.assertFalse(plan_is_usable(snap))


if __name__ == "__main__":
    unittest.main()
