import unittest
from datetime import date

from storage import Expense
from summary import monthly_totals


def spend(day: str, amount: float, category: str = "food") -> Expense:
    return Expense(date.fromisoformat(day), amount, category)


class MonthlyTotalsTest(unittest.TestCase):
    def test_empty_list_gives_empty_dict(self):
        self.assertEqual(monthly_totals([]), {})

    def test_one_expense(self):
        self.assertEqual(monthly_totals([spend("2026-11-03", 12.5)]), {"2026-11": 12.5})

    def test_same_month_is_added_up(self):
        result = monthly_totals([spend("2026-11-03", 12.5), spend("2026-11-28", 7.5)])
        self.assertEqual(result, {"2026-11": 20.0})

    def test_same_month_in_different_years_stays_apart(self):
        result = monthly_totals([spend("2025-11-10", 5.0), spend("2026-11-10", 8.0)])
        self.assertEqual(result, {"2025-11": 5.0, "2026-11": 8.0})

    def test_months_come_out_in_date_order(self):
        result = monthly_totals([
            spend("2026-02-01", 1.0),
            spend("2025-12-31", 2.0),
            spend("2026-01-15", 3.0),
        ])
        self.assertEqual(list(result), ["2025-12", "2026-01", "2026-02"])

    def test_totals_are_rounded_to_cents(self):
        result = monthly_totals([spend("2026-01-01", 0.10), spend("2026-01-02", 0.20)])
        self.assertEqual(result["2026-01"], 0.3)


if __name__ == "__main__":
    unittest.main()
