#!/usr/bin/env python3
"""Pre-release checks. Run before tagging a release:  python3 scripts/preflight.py

Checks the skill format, both READMEs, the demo task, the test log and (if this is a
git repo) the GitHub remote. Exits non-zero if anything must be fixed first.
Python 3.8+, standard library only.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OWNER, NAME = "gugusiyuan49", "i-miss-coding"
INSTALL = f"npx skills add {OWNER}/{NAME}"
failed = 0


def report(ok, what: str, fix: str = "") -> None:
    """ok: True pass, False must fix, None worth a look."""
    global failed
    mark = {True: "PASS", False: "FAIL", None: "WARN"}[ok]
    failed += ok is False
    print(f"[{mark}] {what}" + (f"\n       -> {fix}" if fix and ok is not True else ""))


def run(cmd, cwd=REPO, timeout=120):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout + p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def check_skill() -> None:
    path = REPO / "skills" / NAME / "SKILL.md"
    if not path.exists():
        return report(False, "SKILL.md exists", f"expected at {path.relative_to(REPO)}")
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return report(False, "SKILL.md has YAML frontmatter")
    fields = dict(re.findall(r"^([a-z-]+):[ \t]*(.*)$", m.group(1), re.M))
    name, desc = fields.get("name", ""), fields.get("description", "")
    report(bool(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name)) and len(name) <= 64 and name == path.parent.name,
           f"skill name '{name}' is valid and matches its folder")
    report(0 < len(desc) <= 1024, f"description is {len(desc)} chars (limit 1024)")
    report(": " not in desc and " #" not in desc, "description is a plain one-line YAML value",
           "avoid ': ' and ' #' so every agent's parser reads it the same way")
    lines = len(text.splitlines())
    report(lines <= 80, f"SKILL.md is {lines} lines (plan limit 80)")


def section(text: str, heading: str) -> str:
    m = re.search(rf"^## {heading}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1) if m else ""


def check_readme(file: str, other: str, tested_heading: str, pending: str) -> None:
    path = REPO / file
    if not path.exists():
        return report(False, f"{file} exists")
    text = path.read_text(encoding="utf-8")
    visible = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    report(INSTALL in text, f"{file}: install command uses the real username")
    report("YOUR_NAME" not in text and not re.search(r"<[^<>\n]*\.\.\.[^<>\n]*>", visible),
           f"{file}: no template placeholders left")
    report(other in text, f"{file}: links to {other}")
    for img in re.findall(r"!\[[^\]]*\]\(([^)\s]+)\)", text):
        target = REPO / img
        if not target.exists():
            report(False, f"{file}: image {img} exists")
        elif target.suffix == ".gif":
            mb = target.stat().st_size / 1e6
            report(mb < 5, f"{file}: {img} is {mb:.2f} MB (keep under 5 MB)")
    tested = section(text, tested_heading)
    runs = [l for l in tested.splitlines() if l.startswith("- ") and re.search(r"20\d\d-\d\d-\d\d", l)]
    report(pending not in text and len(runs) >= 2,
           f"{file}: '{tested_heading}' lists {len(runs)} real runs (need 2+)",
           "run python3 scripts/eval.py on two agents, then list them with version and date")


def check_demo() -> None:
    demo = REPO / "examples" / "demo-task"
    gaps = sum(p.read_text(encoding="utf-8").count("TODO(human)") for p in demo.glob("*.py"))
    report(gaps == 1, f"demo-task has exactly one TODO(human) (found {gaps})")
    code, _ = run([sys.executable, "-m", "unittest"], cwd=demo)
    report(code != 0, "demo-task tests fail while the gap is open")


def check_log() -> None:
    log = REPO / "examples" / "test-log.md"
    runs = re.findall(r"^## 20\d\d-\d\d-\d\d · (\w+)", log.read_text(encoding="utf-8"), re.M) if log.exists() else []
    report(len(set(runs)) >= 2, f"test-log.md has runs from {len(set(runs))} agent(s) (need 2+)",
           "python3 scripts/eval.py codex   and   python3 scripts/eval.py claude (or gemini)")


def check_git() -> None:
    if not (REPO / ".git").exists():
        return report(None, "not a git repo yet", "run launch-kit/publish.sh")
    _, url = run(["git", "remote", "get-url", "origin"])
    report(f"{OWNER}/{NAME}" in url, "git remote origin points at GitHub", "git remote add origin ...")
    _, status = run(["git", "status", "--porcelain"])
    report(status.strip() == "", "no uncommitted changes", "commit and push before tagging")
    code, _ = run(["git", "ls-remote", f"https://github.com/{OWNER}/{NAME}.git", "HEAD"], timeout=30)
    report(True if code == 0 else None, "GitHub repo is reachable", "push it, and make sure it is Public")


def check_install() -> None:
    if not shutil.which("npx"):
        return report(None, "npx not found, skipped the install check", "install Node.js 18+")
    code, out = run(["npx", "-y", "skills", "add", str(REPO), "--list"], cwd=Path.home(), timeout=180)
    report(code == 0 and NAME in out, "`npx skills add` finds the skill in this repo")


if __name__ == "__main__":
    print(f"Preflight for {OWNER}/{NAME}\n")
    check_skill()
    check_readme("README.md", "README.zh-CN.md", "Tested on", "Testing in progress")
    check_readme("README.zh-CN.md", "README.md", "测试过的 agent", "测试进行中")
    check_demo()
    check_log()
    check_git()
    check_install()
    print(f"\n{'All clear.' if not failed else f'{failed} thing(s) to fix before release.'}")
    sys.exit(1 if failed else 0)
