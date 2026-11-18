"""Reading and writing expenses as a small CSV file."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

FIELDS = ["date", "amount", "category"]


@dataclass(frozen=True)
class Expense:
    day: date
    amount: float
    category: str


def load(path: Path) -> list[Expense]:
    """Return every expense in the file, or an empty list if the file doesn't exist yet."""
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [
            Expense(date.fromisoformat(row["date"]), float(row["amount"]), row["category"])
            for row in csv.DictReader(f)
        ]


def append(path: Path, expense: Expense) -> None:
    """Add one expense to the end of the file, creating it with a header if needed."""
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(FIELDS)
        writer.writerow([expense.day.isoformat(), f"{expense.amount:.2f}", expense.category])
