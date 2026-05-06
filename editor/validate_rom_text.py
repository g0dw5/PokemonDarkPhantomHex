from __future__ import annotations

import json
import sys
from pathlib import Path

from rom_data import ROOT, extract_rom_text


CASES_PATH = ROOT / "data" / "rom_text_validation_cases.json"


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：python3 editor/validate_rom_text.py /path/to/game.gba")
        return 2
    data = extract_rom_text(Path(sys.argv[1]).expanduser())
    expected_names = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    failed = []
    total = 0
    for table, cases in expected_names.items():
        for item_id, expected in cases.items():
            item_id = int(item_id)
            total += 1
            entry = data[table][str(item_id)]
            decoded = entry["decoded"]
            ok = decoded == expected
            status = "OK" if ok else "FAIL"
            print(
                f"{status} {table} {item_id}: decoded={decoded!r} expected={expected!r} "
                f"tokens={' '.join(entry['tokens'])}"
            )
            if not ok:
                failed.append((table, item_id, decoded, expected))
    print(f"验证：{total - len(failed)} / {total} 通过")
    if failed:
        print("失败项表示当前字符码表或特殊显示规则尚未解释，不自动覆盖主显示名。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
