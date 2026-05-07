from __future__ import annotations

import ast
import sys
import threading
import unittest
from pathlib import Path
from types import FrameType


ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    ROOT / "editor" / "pokemon_save_core.py",
    ROOT / "editor" / "web_save_editor.py",
]
MIN_COVERAGE = 90.0


class LineCoverage:
    def __init__(self, targets: list[Path]):
        self.targets = {str(path.resolve()): path for path in targets}
        self.executable = {str(path.resolve()): executable_lines(path) for path in targets}
        self.executed: dict[str, set[int]] = {str(path.resolve()): set() for path in targets}
        self.filename_cache: dict[str, str] = {}

    def trace(self, frame: FrameType, event: str, _arg):
        if event == "call":
            filename = self.canonical_filename(frame.f_code.co_filename)
            return self.trace if filename in self.executed else None
        if event == "line":
            filename = self.canonical_filename(frame.f_code.co_filename)
            if filename in self.executed:
                self.executed[filename].add(frame.f_lineno)
        return self.trace

    def canonical_filename(self, filename: str) -> str:
        cached = self.filename_cache.get(filename)
        if cached is None:
            cached = str(Path(filename).resolve())
            self.filename_cache[filename] = cached
        return cached

    def report(self) -> tuple[float, list[str]]:
        lines: list[str] = []
        total_executable = 0
        total_executed = 0
        for filename, path in self.targets.items():
            executable = self.executable[filename]
            executed = self.executed[filename] & executable
            total_executable += len(executable)
            total_executed += len(executed)
            percent = 100.0 if not executable else len(executed) * 100.0 / len(executable)
            lines.append(f"{path.relative_to(ROOT)}: {percent:.1f}% ({len(executed)}/{len(executable)})")
            missing = sorted(executable - executed)
            if missing:
                lines.append(f"  missing: {', '.join(str(line) for line in missing[:30])}{' ...' if len(missing) > 30 else ''}")
        total = 100.0 if not total_executable else total_executed * 100.0 / total_executable
        lines.append(f"TOTAL: {total:.1f}% ({total_executed}/{total_executable})")
        return total, lines


def executable_lines(path: Path) -> set[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt):
            lines.add(node.lineno)
    return lines


def main() -> int:
    coverage = LineCoverage(TARGETS)
    sys.settrace(coverage.trace)
    threading.settrace(coverage.trace)
    try:
        backend_suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_editor_backend.py")
        backend_result = unittest.TextTestRunner(verbosity=2).run(backend_suite)
    finally:
        sys.settrace(None)
        threading.settrace(None)

    browser_suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_web_editor_browser.py")
    browser_result = unittest.TextTestRunner(verbosity=2).run(browser_suite)

    total, report_lines = coverage.report()
    print("\nCoverage:")
    for line in report_lines:
        print(f"  {line}")
    if total < MIN_COVERAGE:
        print(f"\nCoverage below required {MIN_COVERAGE:.1f}%")
        return 1
    return 0 if backend_result.wasSuccessful() and browser_result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
