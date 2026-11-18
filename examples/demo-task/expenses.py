"""A tiny command-line expense tracker.

    python3 expenses.py add 2026-11-03 12.50 food
    python3 expenses.py list
    python3 expenses.py summary
    python3 expenses.py --file sample.csv summary
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import storage
from summary import format_table, monthly_totals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Track spending and total it by month.")
    parser.add_argument("--file", type=Path, default=Path("expenses.csv"),
                        help="CSV file to read and write (default: expenses.csv)")
    commands = parser.add_subparsers(dest="command", required=True)

    add = commands.add_parser("add", help="record one expense")
    add.add_argument("day", type=date.fromisoformat, help="date as YYYY-MM-DD")
    add.add_argument("amount", type=float, help="amount spent, e.g. 12.50")
    add.add_argument("category", help="a word like food, rent or transport")
    commands.add_parser("list", help="show every expense")
    commands.add_parser("summary", help="total the spending for each month")

    args = parser.parse_args(argv)

    if args.command == "add":
        storage.append(args.file, storage.Expense(args.day, args.amount, args.category))
        print(f"Added {args.amount:.2f} for {args.category} on {args.day}.")
    elif args.command == "list":
        for e in storage.load(args.file):
            print(f"{e.day}  {e.amount:>8.2f}  {e.category}")
    else:
        try:
            totals = monthly_totals(storage.load(args.file))
        except NotImplementedError:
            print("monthly_totals() in summary.py is your part and isn't written yet.")
            print("Check it with: python3 -m unittest")
            return 1
        print(format_table(totals))
    return 0


if __name__ == "__main__":
    sys.exit(main())
