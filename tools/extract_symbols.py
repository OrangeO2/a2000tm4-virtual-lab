#!/usr/bin/env python3
"""从 Keil ARMCC 链接器 .map 文件提取全局符号地址 → JSON。

用途：FIL 测试需要知道固件显示缓冲（digit/led）的 RAM 地址，
从课程工程 Listings/*.map 提取后放入 firmware/local/symbols.json。

用法：
    python tools/extract_symbols.py adc_demo.map -o firmware/local/symbols.json \
        --names digit led ADC_value

Keil map 的 Global Symbols 段形如：
        digit                          0x20000004   Data           4  adc_demo.o(.bss)
"""

from __future__ import annotations

import argparse
import json
import re
import sys

LINE_RE = re.compile(r"^\s*(\w+)\s+(0x[0-9A-Fa-f]{8})\s+(?:Data|Code|Zero)")


def parse_map(path: str) -> dict[str, int]:
    symbols: dict[str, int] = {}
    in_globals = False
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if "Global Symbols" in line:
                in_globals = True
                continue
            if not in_globals:
                continue
            m = LINE_RE.match(line)
            if m:
                name, addr = m.group(1), int(m.group(2), 16)
                symbols.setdefault(name, addr)
    return symbols


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mapfile", help="Keil .map 文件路径")
    ap.add_argument("-o", "--output", required=True, help="输出 JSON 路径")
    ap.add_argument("--names", nargs="*", default=["digit", "led"],
                    help="关心的符号名（默认 digit led）")
    args = ap.parse_args()

    all_syms = parse_map(args.mapfile)
    picked = {n: all_syms[n] for n in args.names if n in all_syms}
    missing = [n for n in args.names if n not in all_syms]
    if missing:
        print(f"警告: 未找到符号 {missing}（检查 map 是否为该工程生成）", file=sys.stderr)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(picked, f, ensure_ascii=False, indent=2)
    print(f"已写入 {args.output}: {picked}")
    return 0 if picked else 1


if __name__ == "__main__":
    sys.exit(main())
