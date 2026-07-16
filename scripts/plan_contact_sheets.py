#!/usr/bin/env python3
"""Plan fast representative previews or opt-in full-deck contact sheets."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass


MAX_SLIDES_PER_SHEET = 12
MAX_REPRESENTATIVE_PAGES = 4
REPRESENTATIVE_ROLES = ("cover", "context", "method", "result")


@dataclass(frozen=True)
class SheetPlan:
    part: int
    slides: int
    columns: int
    rows: int
    page_numbers: list[int]


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("slide_count must be a positive integer")
    return parsed


def grid_for(slides: int) -> tuple[int, int]:
    if slides == 1:
        return 1, 1
    if slides == 2:
        return 2, 1
    if slides <= 4:
        return 2, 2
    if slides <= 6:
        return 3, 2
    if slides <= 9:
        return 3, 3
    if slides <= MAX_SLIDES_PER_SHEET:
        return 4, 3
    raise ValueError(f"A contact sheet cannot contain more than {MAX_SLIDES_PER_SHEET} slides")


def parse_page_list(raw: str | None, slide_count: int) -> list[int] | None:
    if raw is None:
        return None
    tokens = [token for token in re.split(r"[\s,;]+", raw.strip()) if token]
    if not tokens:
        raise argparse.ArgumentTypeError("--pages must contain at least one page number")
    try:
        pages = [int(token) for token in tokens]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--pages must contain only integers") from exc
    if len(pages) > MAX_REPRESENTATIVE_PAGES:
        raise argparse.ArgumentTypeError("representative mode accepts at most four pages")
    if len(set(pages)) != len(pages):
        raise argparse.ArgumentTypeError("--pages must not contain duplicates")
    invalid = [page for page in pages if page < 1 or page > slide_count]
    if invalid:
        raise argparse.ArgumentTypeError(
            f"representative pages must be within 1..{slide_count}: {invalid}"
        )
    return pages


def positional_fallback(slide_count: int) -> list[int]:
    if slide_count <= MAX_REPRESENTATIVE_PAGES:
        return list(range(1, slide_count + 1))
    pages = [
        1,
        1 + round((slide_count - 1) / 3),
        1 + round(2 * (slide_count - 1) / 3),
        slide_count,
    ]
    return list(dict.fromkeys(pages))


def build_representative_plan(slide_count: int, pages: list[int] | None) -> dict[str, object]:
    selected = pages or positional_fallback(slide_count)
    columns, rows = grid_for(len(selected))
    part = SheetPlan(
        part=1,
        slides=len(selected),
        columns=columns,
        rows=rows,
        page_numbers=selected,
    )
    return {
        "mode": "representative",
        "slide_count": slide_count,
        "page_number_width": max(2, len(str(slide_count))),
        "selection_basis": "semantic_pages_provided" if pages else "positional_fallback",
        "preview_pages": selected,
        "recommended_roles": list(REPRESENTATIVE_ROLES[: len(selected)]),
        "sheets_per_style": 1,
        "total_sheets_for_four_styles": 4,
        "parts": [asdict(part)],
        "warning": None if pages else (
            "Positional fallback was used. Prefer passing four semantically selected pages "
            "for cover, context, method, and result roles."
        ),
    }


def build_full_plan(slide_count: int) -> dict[str, object]:
    sheet_count = (slide_count + MAX_SLIDES_PER_SHEET - 1) // MAX_SLIDES_PER_SHEET
    base, extra = divmod(slide_count, sheet_count)
    sizes = [base + (1 if index < extra else 0) for index in range(sheet_count)]

    plans: list[SheetPlan] = []
    start_page = 1
    for index, size in enumerate(sizes, start=1):
        columns, rows = grid_for(size)
        page_numbers = list(range(start_page, start_page + size))
        plans.append(
            SheetPlan(
                part=index,
                slides=size,
                columns=columns,
                rows=rows,
                page_numbers=page_numbers,
            )
        )
        start_page += size

    return {
        "mode": "full",
        "slide_count": slide_count,
        "page_number_width": max(2, len(str(slide_count))),
        "max_slides_per_sheet": MAX_SLIDES_PER_SHEET,
        "sheets_per_style": sheet_count,
        "total_sheets_for_four_styles": sheet_count * 4,
        "parts": [asdict(plan) for plan in plans],
    }


def build_plan(slide_count: int, mode: str, pages: list[int] | None = None) -> dict[str, object]:
    if mode == "representative":
        return build_representative_plan(slide_count, pages)
    if pages:
        raise ValueError("--pages is only valid in representative mode")
    return build_full_plan(slide_count)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Plan four representative style previews by default, or opt in to "
            "balanced full-deck contact sheets."
        )
    )
    parser.add_argument("slide_count", type=positive_int)
    parser.add_argument(
        "--mode",
        choices=("representative", "full"),
        default="representative",
    )
    parser.add_argument(
        "--pages",
        help="Comma-separated semantic preview pages; representative mode only, max four.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a table")
    args = parser.parse_args()
    try:
        args.pages = parse_page_list(args.pages, args.slide_count)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    return args


def main() -> int:
    args = parse_args()
    try:
        plan = build_plan(args.slide_count, args.mode, args.pages)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    print(f"Mode: {plan['mode']}")
    print(f"Slide count: {plan['slide_count']}")
    print(f"Contact sheets per style: {plan['sheets_per_style']}")
    print(f"Total sheets for A-D: {plan['total_sheets_for_four_styles']}")
    print("Part  Slides  Pages                 Grid")
    for part in plan["parts"]:
        pages = ",".join(str(page) for page in part["page_numbers"])
        grid = f"{part['columns']}x{part['rows']}"
        print(f"{part['part']:>4}  {part['slides']:>6}  {pages:<20}  {grid}")
    if plan.get("warning"):
        print(f"Warning: {plan['warning']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
