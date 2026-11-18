#!/usr/bin/env python3
"""Run the i-miss-coding test tasks on a coding agent and check what it did.

    python3 scripts/eval.py claude        # Claude Code
    python3 scripts/eval.py codex         # Codex CLI
    python3 scripts/eval.py gemini        # Gemini CLI
    python3 scripts/eval.py codex --tasks t1 t3
    python3 scripts/eval.py claude --dry-run

Tasks (one fresh session each):
    T1  build a CLI expense tracker -> one TODO(human), failing tests;
        then "hint" x3, a wrong answer + "done", and finally
    T4  "还是你写吧" (you write it) -> the agent finishes, tests pass
    T2  build a pomodoro web page   -> one TODO(human), failing tests
    T3  rename a variable           -> no gap, just done

Every task runs in its own temporary folder with the skill installed at project
level, so nothing outside that folder is touched. The agent runs there without
permission prompts (Claude Code: acceptEdits + Bash, Codex: workspace-write
sandbox, Gemini CLI: yolo). Replies and the final files are saved to
eval-runs/<agent>-<time>/, and a summary table is appended to
examples/test-log.md. Python 3.8+, standard library only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "skills" / "i-miss-coding"
LOG = REPO / "examples" / "test-log.md"

TASKS = {
    "t1": "用 Python 写一个命令行记账工具，能按月汇总支出",
    "t2": "做一个番茄钟网页",
    "t3": "把 utils.py 里的变量 data 重命名为 records",
}
T3_SEED = '''data = [3, 1, 2]


def total():
    return sum(data)


def largest():
    return max(data) if data else None
'''

INVOKE = {  # how each agent is asked to use the skill
    "claude": "/i-miss-coding {task}",
    "codex": "$i-miss-coding {task}",
    "gemini": "i-miss-coding: leave the core to me. {task}",
}
SKILL_DIRS = {
    "claude": [".claude/skills"],
    "codex": [".agents/skills"],
    "gemini": [".agents/skills"],
}
CODE_SUFFIXES = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html", ".css", ".java",
    ".c", ".cc", ".cpp", ".h", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".cs", ".sh",
}
SKIP_PARTS = {".git", "node_modules", "__pycache__", ".claude", ".agents", ".gemini",
              ".venv", "venv", ".pytest_cache"}
RUNNERS = {"python", "python3", "pytest", "node", "npm", "npx", "pnpm", "yarn", "bun",
           "deno", "go", "cargo"}


class Agent:
    def __init__(self, name: str, binary: str, timeout: int, inline: bool):
        self.name, self.bin, self.timeout, self.inline = name, binary, timeout, inline
        self.session = str(uuid.uuid4())
        self.turn = 0

    def command(self, prompt: str) -> list[str]:
        first = self.turn == 0
        if self.name == "claude":
            cmd = [self.bin, "-p", prompt, "--permission-mode", "acceptEdits",
                   "--allowedTools", "Bash", "Skill", "--output-format", "text"]
            return cmd + (["--session-id", self.session] if first else ["--resume", self.session])
        if self.name == "codex":
            base = [self.bin, "exec", "--skip-git-repo-check", "--sandbox", "workspace-write"]
            return base + ([prompt] if first else ["resume", "--last", prompt])
        cmd = [self.bin, "-p", prompt, "--approval-mode", "yolo", "-o", "text"]
        return cmd if first else cmd + ["--resume", "latest"]

    def send(self, work: Path, prompt: str, dry: bool) -> str:
        if self.turn == 0 and self.inline:
            prompt = ("Follow these instructions for the whole session:\n\n"
                      + skill_body() + "\n\nTask: " + prompt)
        cmd = self.command(prompt)
        self.turn += 1
        if dry:
            return "[dry run] " + " ".join(cmd)
        out = run(cmd, work, self.timeout)
        if self.name == "codex" and self.turn > 1 and out.code == 2:
            # older Codex builds only take flags after `resume`
            out = run([self.bin, "exec", "resume", "--last", prompt], work, self.timeout)
        return out.text


class Result:
    def __init__(self, code: int, text: str):
        self.code, self.text = code, text


def run(cmd, cwd: Path, timeout: int, shell: bool = False) -> Result:
    try:
        p = subprocess.run(cmd, cwd=cwd, shell=shell, capture_output=True, text=True,
                           timeout=timeout, stdin=subprocess.DEVNULL)
        return Result(p.returncode, (p.stdout + ("\n" + p.stderr if p.stderr.strip() else "")).strip())
    except subprocess.TimeoutExpired:
        return Result(124, f"[timed out after {timeout}s]")
    except FileNotFoundError:
        return Result(127, f"[command not found: {cmd if isinstance(cmd, str) else cmd[0]}]")


def skill_body() -> str:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    return re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S).strip()


def make_workspace(root: Path, agent: str, task: str) -> Path:
    work = root / task
    work.mkdir(parents=True)
    for rel in SKILL_DIRS[agent]:
        shutil.copytree(SKILL, work / rel / SKILL.name)
    if task == "t3":
        (work / "utils.py").write_text(T3_SEED, encoding="utf-8")
    run(["git", "init", "-q"], work, 30)
    return work


def code_files(work: Path):
    for path in sorted(work.rglob("*")):
        rel = path.relative_to(work)
        if path.is_file() and path.suffix in CODE_SUFFIXES and not SKIP_PARTS.intersection(rel.parts):
            yield path


def gap_sites(work: Path) -> list[tuple[Path, int]]:
    """Places marked TODO(human); marker lines within 12 lines of each other count once."""
    sites: list[list] = []
    for path in code_files(work):
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for n, line in enumerate(lines, 1):
            if "TODO(human)" not in line:
                continue
            if sites and sites[-1][0] == path and n - sites[-1][2] <= 12:
                sites[-1][2] = n
            else:
                sites.append([path, n, n])
    return [(p, first) for p, first, _ in sites]


def test_command(work: Path, transcript: str) -> str | None:
    for m in re.finditer(r"(?:Check it with|检查|验证|测试|运行)[^`\n]*`([^`\n]+)`", transcript):
        cmd = m.group(1).strip()
        if cmd.split()[0] in RUNNERS:
            return cmd
    files = list(code_files(work))
    if any(re.match(r"(test_.+|.+_test)\.py$", p.name) for p in files):
        if run([sys.executable, "-c", "import pytest"], work, 30).code == 0:
            return f"{sys.executable} -m pytest -q"
        dirs = sorted({str(p.parent.relative_to(work)) for p in files if p.name.startswith("test")})
        return f"{sys.executable} -m unittest discover -s {dirs[0] if dirs else '.'} -t ."
    pkg = work / "package.json"
    if pkg.exists() and '"test"' in pkg.read_text(encoding="utf-8", errors="replace"):
        return "npm test --silent"
    if any(re.search(r"\.(test|spec)\.[mc]?js$", p.name) or "test" in p.parent.name for p in files
           if p.suffix in {".js", ".mjs", ".cjs"}):
        return "node --test"
    return None


def tests_state(work: Path, transcript: str) -> tuple[str, str]:
    cmd = test_command(work, transcript)
    if not cmd:
        return "none", "no tests or check command found"
    out = run(cmd, work, 300, shell=True)
    return ("green" if out.code == 0 else "red"), f"`{cmd}` exit {out.code}"


def break_the_gap(work: Path, handover: str) -> tuple[Path, str] | None:
    """Fill the gap with a wrong answer, the way a human with a bug would."""
    named_first = sorted(gap_sites(work), key=lambda site: site[0].name not in handover)
    for path, line_no in named_first:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        for i in range(line_no - 1, min(line_no + 30, len(lines))):
            m = re.match(r"(\s*)(raise NotImplementedError|throw new Error|throw Error)", lines[i])
            if m:
                wrong = m.group(1) + ("return None  # first attempt" if path.suffix == ".py"
                                      else "return null; // first attempt")
                lines[i] = wrong + "\n"
                path.write_text("".join(lines), encoding="utf-8")
                return path, wrong.strip()
    return None


class Report:
    def __init__(self):
        self.rows: list[tuple[str, str, str, str]] = []

    def check(self, task: str, what: str, ok, note: str = "") -> None:
        mark = "PASS" if ok is True else "FAIL" if ok is False else "SKIP"
        self.rows.append((task, what, mark, note))
        print(f"  [{mark}] {task} {what}" + (f" ({note})" if note else ""))


def run_t1(agent: Agent, work: Path, rep: Report, out_dir: Path, dry: bool) -> None:
    replies = []

    def say(msg: str) -> str:
        print(f"  > {msg[:70]}")
        reply = agent.send(work, msg, dry)
        replies.append((msg, reply))
        return reply

    first = say(INVOKE[agent.name].format(task=TASKS["t1"]))
    if dry:
        for msg in ["hint", "hint", "hint", "done", "还是你写吧"]:
            say(msg)
        save(out_dir / "t1", work, replies)
        return
    sites = gap_sites(work)
    rep.check("T1", "exactly one TODO(human)", len(sites) == 1, f"{len(sites)} found")
    state, note = tests_state(work, first)
    rep.check("T1", "tests fail at handover", state == "red" if state != "none" else None, note)
    for _ in range(3):
        say("hint")
    after = gap_sites(work)
    rep.check("T1", "gap still open after 3 hints", len(after) == len(sites) >= 1)
    broken = break_the_gap(work, first)
    say("done")
    if broken:
        path, wrong = broken
        kept = wrong in path.read_text(encoding="utf-8")
        rep.check("T1", "wrong answer + done: reviewed, not rewritten", kept,
                  "agent left the human's code alone" if kept else "agent replaced the human's code")
    else:
        rep.check("T1", "wrong answer + done: reviewed, not rewritten", None, "no stub line to replace")
    final = say("还是你写吧")
    rep.check("T4", "'you write it': gap filled", len(gap_sites(work)) == 0)
    state, note = tests_state(work, first + "\n" + final)
    rep.check("T4", "'you write it': tests pass", state == "green" if state != "none" else None, note)
    save(out_dir / "t1", work, replies)


def run_t2(agent: Agent, work: Path, rep: Report, out_dir: Path, dry: bool) -> None:
    reply = agent.send(work, INVOKE[agent.name].format(task=TASKS["t2"]), dry)
    if not dry:
        sites = gap_sites(work)
        rep.check("T2", "exactly one TODO(human)", len(sites) == 1, f"{len(sites)} found")
        state, note = tests_state(work, reply)
        rep.check("T2", "tests or check fail at handover", state == "red" if state != "none" else None, note)
    save(out_dir / "t2", work, [(TASKS["t2"], reply)])


def run_t3(agent: Agent, work: Path, rep: Report, out_dir: Path, dry: bool) -> None:
    reply = agent.send(work, INVOKE[agent.name].format(task=TASKS["t3"]), dry)
    if not dry:
        rep.check("T3", "no gap for a plain rename", len(gap_sites(work)) == 0)
        src = (work / "utils.py").read_text(encoding="utf-8")
        renamed = "records" in src and not re.search(r"\bdata\b", src)
        works = run([sys.executable, "-c", "import utils; assert utils.total() == 6"], work, 30).code == 0
        rep.check("T3", "rename done and code still runs", renamed and works)
    save(out_dir / "t3", work, [(TASKS["t3"], reply)])


def save(dest: Path, work: Path, replies) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with (dest / "transcript.txt").open("w", encoding="utf-8") as f:
        for i, (msg, reply) in enumerate(replies, 1):
            f.write(f"===== turn {i} | you: {msg}\n\n{reply}\n\n")
    shutil.copytree(work, dest / "files", ignore=shutil.ignore_patterns(*SKIP_PARTS), dirs_exist_ok=True)


def append_log(agent: str, version: str, rep: Report, out_dir: Path) -> None:
    today = dt.date.today().isoformat()
    passed = sum(r[2] == "PASS" for r in rep.rows)
    lines = [f"\n## {today} · {agent} · {version}\n",
             f"Automatic checks: {passed}/{len(rep.rows)} passed. "
             f"Transcripts: `{out_dir.relative_to(REPO)}/` (local only).\n",
             "| Task | Check | Result | Note |", "| --- | --- | --- | --- |"]
    lines += [f"| {t} | {w} | {m} | {n} |" for t, w, m, n in rep.rows]
    lines += ["", "Read the transcripts and tick by hand:", "",
              "- [ ] the gap is the real core, not a side detail",
              "- [ ] the rest ran up to the gap",
              "- [ ] no answer code in the chat before the hint ladder reached it",
              "- [ ] the review after `done` had at most 3 points",
              "- [ ] hints went idea -> pseudocode -> code", ""]
    if not LOG.exists():
        LOG.write_text("# Test log\n\nResults from `python3 scripts/eval.py <agent>`.\n", encoding="utf-8")
    with LOG.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("agent", choices=sorted(INVOKE))
    ap.add_argument("--tasks", nargs="+", choices=["t1", "t2", "t3"], default=["t1", "t2", "t3"],
                    help="which tasks to run (t1 includes T4)")
    ap.add_argument("--bin", help="path to the agent's executable (default: claude / codex / gemini)")
    ap.add_argument("--timeout", type=int, default=1200, help="seconds per agent turn (default 1200)")
    ap.add_argument("--inline", action="store_true",
                    help="paste the skill text into the first prompt instead of relying on discovery")
    ap.add_argument("--dry-run", action="store_true", help="show the commands without running an agent")
    ap.add_argument("--no-log", action="store_true", help="don't append to examples/test-log.md")
    args = ap.parse_args()

    binary = args.bin or args.agent
    if not args.dry_run and not shutil.which(binary):
        sys.exit(f"Can't find `{binary}` on PATH. Install the agent first, or pass --bin.")
    version = "dry run" if args.dry_run else (run([binary, "--version"], REPO, 60).text.splitlines() or ["?"])[0]
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    out_dir = REPO / "eval-runs" / f"{args.agent}-{stamp}"
    rep = Report()
    print(f"Testing i-miss-coding on {args.agent} ({version})\n")

    with tempfile.TemporaryDirectory(prefix="i-miss-coding-eval-") as tmp:
        for task in args.tasks:
            print(f"{task.upper()}: {TASKS[task]}")
            agent = Agent(args.agent, binary, args.timeout, args.inline)
            work = make_workspace(Path(tmp), args.agent, task)
            {"t1": run_t1, "t2": run_t2, "t3": run_t3}[task](agent, work, rep, out_dir, args.dry_run)
            print()

    if args.dry_run:
        print(f"Dry run done. Commands are in {out_dir.relative_to(REPO)}/*/transcript.txt")
        return 0
    passed = sum(r[2] == "PASS" for r in rep.rows)
    print(f"{passed}/{len(rep.rows)} automatic checks passed. Transcripts: {out_dir.relative_to(REPO)}/")
    if not args.no_log:
        append_log(args.agent, version, rep, out_dir)
        print(f"Summary added to {LOG.relative_to(REPO)} - finish the hand-checked items there.")
    if any(r[:2] == ("T1", "exactly one TODO(human)") and r[3] == "0 found" for r in rep.rows):
        print("Tip: no TODO(human) in T1 usually means the agent didn't load the skill. "
              "Run it again with --inline to test the rules on their own.")
    return 0 if all(r[2] != "FAIL" for r in rep.rows) else 1


if __name__ == "__main__":
    sys.exit(main())
