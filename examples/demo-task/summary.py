"""Monthly summary of expenses."""

from __future__ import annotations

from storage import Expense


def monthly_totals(expenses: list[Expense]) -> dict[str, float]:
    # TODO(human): total the spending for each month.
    #   Input:  a list of Expense(day, amount, category), in any order.
    #   Output: {"YYYY-MM": total, ...} with months in date order,
    #           each total rounded to 2 decimal places.
    #   Edge cases: an empty list gives {}; the same month in two different
    #   years is two different keys; 0.10 + 0.20 should come out as 0.3.
    #   Hint: one dictionary from a month key to a running total is enough.
    raise NotImplementedError("your turn: write monthly_totals()")


def format_table(totals: dict[str, float]) -> str:
    """Render the totals as a small text table with a grand total."""
    if not totals:
        return "No expenses yet."
    lines = [f"{'Month':<9}{'Total':>10}", "-" * 19]
    lines += [f"{month:<9}{amount:>10.2f}" for month, amount in totals.items()]
    lines += ["-" * 19, f"{'All':<9}{sum(totals.values()):>10.2f}"]
    return "\n".join(lines)
