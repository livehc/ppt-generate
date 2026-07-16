#!/usr/bin/env python3
"""Audit raster or hybrid-editable PPTX structure using only the Python stdlib.

Exit codes:
  0: no errors (and no warnings when --fail-on-warning is used)
  1: structural errors were found
  2: warnings were found and --fail-on-warning was used
"""

from __future__ import annotations

import argparse
import json
import math
import posixpath
import re
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
C_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
DGM_NS = "http://schemas.openxmlformats.org/drawingml/2006/diagram"

NS = {
    "p": P_NS,
    "a": A_NS,
    "r": R_NS,
    "rel": REL_NS,
    "c": C_NS,
    "dgm": DGM_NS,
}

EMU_PER_INCH = 914400
TARGET_RATIO = 16 / 9


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit slide count, 16:9 canvas, image coverage, and editable objects."
    )
    parser.add_argument("pptx", type=Path, help="PPTX file to inspect")
    parser.add_argument(
        "--profile",
        choices=("image", "editable"),
        required=True,
        help="Expected deck type: full-slide raster pages or hybrid editable pages",
    )
    parser.add_argument(
        "--expect-slides", type=int, default=None, help="Require an exact slide count"
    )
    parser.add_argument(
        "--min-editable-chars",
        type=int,
        default=12,
        help="Editable-profile minimum non-whitespace text characters per slide",
    )
    parser.add_argument(
        "--ratio-tolerance",
        type=float,
        default=0.002,
        help="Allowed absolute deviation from the 16:9 width/height ratio",
    )
    parser.add_argument(
        "--json", action="store_true", help="Print machine-readable JSON only"
    )
    parser.add_argument(
        "--json-output", type=Path, help="Also save the JSON report to this path"
    )
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Return exit code 2 when warnings remain and no errors exist",
    )
    return parser.parse_args()


def read_xml(archive: zipfile.ZipFile, member: str) -> ET.Element:
    try:
        return ET.fromstring(archive.read(member))
    except KeyError as exc:
        raise ValueError(f"Missing required OOXML member: {member}") from exc
    except ET.ParseError as exc:
        raise ValueError(f"Invalid XML in OOXML member: {member}") from exc


def numeric_slide_key(name: str) -> tuple[int, str]:
    match = re.search(r"slide(\d+)\.xml$", name)
    return (int(match.group(1)) if match else math.inf, name)


def ordered_slide_members(
    archive: zipfile.ZipFile, presentation: ET.Element
) -> list[str]:
    rels_root = read_xml(archive, "ppt/_rels/presentation.xml.rels")
    relationships = {
        rel.attrib.get("Id", ""): rel.attrib.get("Target", "")
        for rel in rels_root.findall("rel:Relationship", NS)
    }

    ordered: list[str] = []
    for slide_id in presentation.findall("./p:sldIdLst/p:sldId", NS):
        rel_id = slide_id.attrib.get(f"{{{R_NS}}}id", "")
        target = relationships.get(rel_id, "")
        if not target:
            continue
        if target.startswith("/"):
            member = target.lstrip("/")
        else:
            member = posixpath.normpath(posixpath.join("ppt", target))
        if member in archive.namelist():
            ordered.append(member)

    if ordered:
        return ordered

    return sorted(
        (
            name
            for name in archive.namelist()
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
        ),
        key=numeric_slide_key,
    )


def int_attr(element: ET.Element | None, name: str) -> int | None:
    if element is None:
        return None
    value = element.attrib.get(name)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def picture_bounds(pic: ET.Element) -> tuple[int, int, int, int] | None:
    xfrm = pic.find("./p:spPr/a:xfrm", NS)
    if xfrm is None:
        return None
    off = xfrm.find("a:off", NS)
    ext = xfrm.find("a:ext", NS)
    x = int_attr(off, "x")
    y = int_attr(off, "y")
    cx = int_attr(ext, "cx")
    cy = int_attr(ext, "cy")
    if None in (x, y, cx, cy):
        return None
    return int(x), int(y), int(cx), int(cy)


def is_full_slide_picture(
    bounds: tuple[int, int, int, int] | None,
    slide_cx: int,
    slide_cy: int,
) -> bool:
    if bounds is None or slide_cx <= 0 or slide_cy <= 0:
        return False
    x, y, cx, cy = bounds
    return (
        x <= slide_cx * 0.015
        and y <= slide_cy * 0.015
        and cx >= slide_cx * 0.97
        and cy >= slide_cy * 0.97
        and x + cx >= slide_cx * 0.985
        and y + cy >= slide_cy * 0.985
    )


def text_for_shape(shape: ET.Element) -> str:
    return "".join(node.text or "" for node in shape.findall(".//a:t", NS))


def inspect_slide(
    root: ET.Element, slide_number: int, slide_cx: int, slide_cy: int
) -> dict[str, Any]:
    shapes = root.findall(".//p:sp", NS)
    pictures = root.findall(".//p:pic", NS)
    connectors = root.findall(".//p:cxnSp", NS)
    graphic_frames = root.findall(".//p:graphicFrame", NS)
    groups = root.findall(".//p:grpSp", NS)

    texts = [text_for_shape(shape) for shape in shapes]
    visible_texts = [text for text in texts if text.strip()]
    editable_chars = sum(len(re.sub(r"\s+", "", text)) for text in visible_texts)

    full_slide_pictures = sum(
        1
        for picture in pictures
        if is_full_slide_picture(picture_bounds(picture), slide_cx, slide_cy)
    )
    tables = sum(1 for frame in graphic_frames if frame.find(".//a:tbl", NS) is not None)
    charts = sum(
        1 for frame in graphic_frames if frame.find(".//c:chart", NS) is not None
    )
    diagrams = sum(
        1 for frame in graphic_frames if frame.find(".//dgm:relIds", NS) is not None
    )

    return {
        "slide": slide_number,
        "editable_text_shapes": len(visible_texts),
        "editable_text_characters": editable_chars,
        "native_shapes": len(shapes),
        "connectors": len(connectors),
        "graphic_frames": len(graphic_frames),
        "tables": tables,
        "charts": charts,
        "diagrams": diagrams,
        "groups": len(groups),
        "pictures": len(pictures),
        "full_slide_pictures": full_slide_pictures,
    }


def issue(
    bucket: list[dict[str, Any]], code: str, message: str, slide: int | None = None
) -> None:
    record: dict[str, Any] = {"code": code, "message": message}
    if slide is not None:
        record["slide"] = slide
    bucket.append(record)


def audit(args: argparse.Namespace) -> dict[str, Any]:
    pptx_path = args.pptx.expanduser().resolve()
    if not pptx_path.is_file():
        raise ValueError(f"PPTX file not found: {pptx_path}")
    if pptx_path.suffix.lower() != ".pptx":
        raise ValueError(f"Expected a .pptx file: {pptx_path}")

    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    try:
        archive_context = zipfile.ZipFile(pptx_path)
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Not a valid PPTX/ZIP package: {pptx_path}") from exc

    with archive_context as archive:
        presentation = read_xml(archive, "ppt/presentation.xml")
        size = presentation.find("p:sldSz", NS)
        slide_cx = int_attr(size, "cx") or 0
        slide_cy = int_attr(size, "cy") or 0
        ratio = slide_cx / slide_cy if slide_cy else 0.0
        members = ordered_slide_members(archive, presentation)
        slides = [
            inspect_slide(read_xml(archive, member), index, slide_cx, slide_cy)
            for index, member in enumerate(members, start=1)
        ]

    if slide_cx <= 0 or slide_cy <= 0:
        issue(errors, "invalid_canvas", "Slide canvas size is missing or invalid.")
    elif abs(ratio - TARGET_RATIO) > args.ratio_tolerance:
        issue(
            errors,
            "wrong_aspect_ratio",
            f"Canvas ratio is {ratio:.5f}; expected 16:9 ({TARGET_RATIO:.5f}).",
        )

    if args.expect_slides is not None and len(slides) != args.expect_slides:
        issue(
            errors,
            "wrong_slide_count",
            f"Found {len(slides)} slides; expected {args.expect_slides}.",
        )

    for slide in slides:
        number = slide["slide"]
        if args.profile == "image":
            if slide["pictures"] == 0:
                issue(
                    errors,
                    "missing_page_image",
                    "Image profile requires at least one picture on the slide.",
                    number,
                )
            if slide["full_slide_pictures"] == 0:
                issue(
                    errors,
                    "page_image_not_full_slide",
                    "No picture covers approximately the full 16:9 slide canvas.",
                    number,
                )
            if slide["editable_text_shapes"] or slide["connectors"] or slide["graphic_frames"]:
                issue(
                    warnings,
                    "image_profile_has_native_objects",
                    "Image deck contains native text/connectors/graphic frames; verify this is intentional.",
                    number,
                )
        else:
            if slide["editable_text_characters"] < args.min_editable_chars:
                issue(
                    errors,
                    "insufficient_editable_text",
                    f"Only {slide['editable_text_characters']} editable non-whitespace characters found; minimum is {args.min_editable_chars}.",
                    number,
                )
            if slide["full_slide_pictures"]:
                if slide["editable_text_characters"] < max(args.min_editable_chars * 2, 24):
                    issue(
                        errors,
                        "flattened_slide_risk",
                        "A full-slide picture is present with little editable text; this resembles a flattened-page reconstruction.",
                        number,
                    )
                else:
                    issue(
                        warnings,
                        "full_slide_background_review",
                        "A full-slide picture is present. Verify it is a text-free complex background, not a baked full page.",
                        number,
                    )
            if slide["native_shapes"] == 0 and slide["connectors"] == 0:
                issue(
                    warnings,
                    "no_native_shapes",
                    "No native shapes or connectors were found; verify that simple visual elements were not flattened unnecessarily.",
                    number,
                )

    total_text = sum(slide["editable_text_characters"] for slide in slides)
    total_pictures = sum(slide["pictures"] for slide in slides)
    total_native = sum(
        slide["native_shapes"] + slide["connectors"] + slide["graphic_frames"]
        for slide in slides
    )
    canvas_inches = {
        "width": round(slide_cx / EMU_PER_INCH, 4) if slide_cx else None,
        "height": round(slide_cy / EMU_PER_INCH, 4) if slide_cy else None,
    }

    return {
        "file": str(pptx_path),
        "profile": args.profile,
        "canvas_emu": {"width": slide_cx, "height": slide_cy},
        "canvas_inches": canvas_inches,
        "aspect_ratio": round(ratio, 6) if ratio else None,
        "is_16_9": bool(ratio and abs(ratio - TARGET_RATIO) <= args.ratio_tolerance),
        "slide_count": len(slides),
        "totals": {
            "editable_text_characters": total_text,
            "pictures": total_pictures,
            "native_objects": total_native,
        },
        "slides": slides,
        "errors": errors,
        "warnings": warnings,
        "status": "FAIL" if errors else "PASS_WITH_WARNINGS" if warnings else "PASS",
    }


def print_human(report: dict[str, Any]) -> None:
    canvas = report["canvas_inches"]
    ratio = report["aspect_ratio"]
    print(f"PPTX audit: {report['file']}")
    print(f"Profile: {report['profile']}")
    print(
        "Canvas: "
        f"{canvas['width']} x {canvas['height']} in; ratio={ratio}; "
        f"16:9={'yes' if report['is_16_9'] else 'no'}"
    )
    print(f"Slides: {report['slide_count']}")
    for slide in report["slides"]:
        print(
            f"  {slide['slide']:02d}: text_shapes={slide['editable_text_shapes']} "
            f"chars={slide['editable_text_characters']} native_shapes={slide['native_shapes']} "
            f"connectors={slide['connectors']} charts={slide['charts']} "
            f"tables={slide['tables']} pictures={slide['pictures']} "
            f"full_slide_pictures={slide['full_slide_pictures']}"
        )
    for label, key in (("ERROR", "errors"), ("WARNING", "warnings")):
        for item in report[key]:
            location = f" slide {item['slide']:02d}" if "slide" in item else ""
            print(f"{label}{location} [{item['code']}]: {item['message']}")
    print(f"Result: {report['status']}")


def main() -> int:
    args = parse_args()
    try:
        report = audit(args)
    except (OSError, ValueError) as exc:
        if args.json:
            print(json.dumps({"status": "ERROR", "message": str(exc)}, ensure_ascii=False))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_output:
        output_path = args.json_output.expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(serialized + "\n", encoding="utf-8")

    if args.json:
        print(serialized)
    else:
        print_human(report)

    if report["errors"]:
        return 1
    if args.fail_on_warning and report["warnings"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
