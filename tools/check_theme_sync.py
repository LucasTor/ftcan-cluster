#!/usr/bin/env python3
"""Verify qml/Theme.qml still matches theme.py.

The two palettes are hand-mirrored while both UI builds exist; this checker
turns silent drift into a failing exit code. Run from the repo root (it's also
part of the pre-deploy sanity ritual):

    poetry run python tools/check_theme_sync.py

Every ``readonly property color|real|int`` in Theme.qml is compared against
the theme.py constant of the same name (camelCase -> UPPER_SNAKE), except the
names in SKIP. Colours compare channel-wise with a half-quantum tolerance
(hex literals only carry 8 bits per channel).
"""

import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import theme  # noqa: E402

QML = os.path.join(REPO, "qml", "Theme.qml")

# QML-only properties with no theme.py counterpart:
#   night/dim   — the QML palette-level night-mode machinery
#   accent      — Azul Boreal accent introduced QML-side (theme.py's ACCENT is
#                 the legacy pre-"Painel Gol" card blue, intentionally unequal)
SKIP = {"night", "dim", "accent"}

NAMED = {"black": (0, 0, 0, 1), "white": (1, 1, 1, 1),
         "transparent": (0, 0, 0, 0)}

TOLERANCE = 0.75 / 255


def camel_to_upper_snake(name):
    return re.sub(r"([A-Z])", r"_\1", name).upper()


def parse_qml_color(expr):
    """Literal colour expression -> RGBA tuple (d(...) wrappers stripped)."""
    expr = expr.strip()
    m = re.fullmatch(r"d\((.*)\)", expr)
    if m:
        expr = m.group(1).strip()
    m = re.fullmatch(r"Qt\.rgba\(([^)]*)\)", expr)
    if m:
        return tuple(float(p) for p in m.group(1).split(","))
    m = re.fullmatch(r'"(#[0-9a-fA-F]{6})"', expr)
    if m:
        h = m.group(1)
        return (int(h[1:3], 16) / 255, int(h[3:5], 16) / 255,
                int(h[5:7], 16) / 255, 1.0)
    m = re.fullmatch(r'"(\w+)"', expr)
    if m and m.group(1) in NAMED:
        return NAMED[m.group(1)]
    return None


def main():
    with open(QML) as f:
        qml = f.read()

    failures, checked = [], 0
    props = re.findall(
        r"readonly property (color|real|int) (\w+): (.+?)\s*$", qml, re.M)
    for kind, name, expr in props:
        if name in SKIP:
            continue
        py_name = camel_to_upper_snake(name)
        if not hasattr(theme, py_name):
            failures.append(f"{name}: no theme.py constant {py_name}")
            continue
        py_val = getattr(theme, py_name)
        if kind == "color":
            qml_val = parse_qml_color(expr)
            if qml_val is None:
                failures.append(f"{name}: unparseable colour {expr!r}")
                continue
            if any(abs(a - b) > TOLERANCE for a, b in zip(qml_val, py_val)):
                failures.append(
                    f"{name}: Theme.qml {tuple(round(v, 4) for v in qml_val)}"
                    f" != theme.{py_name} {py_val}")
        else:
            if abs(float(expr) - float(py_val)) > 1e-9:
                failures.append(
                    f"{name}: Theme.qml {expr} != theme.{py_name} {py_val}")
        checked += 1

    if failures:
        print(f"theme drift — {len(failures)} mismatch(es) "
              f"({checked} properties checked):")
        for f_ in failures:
            print(f"  {f_}")
        return 1
    print(f"OK: Theme.qml matches theme.py ({checked} properties checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
