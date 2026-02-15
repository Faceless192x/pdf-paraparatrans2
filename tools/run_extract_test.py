import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MODULES_DIR = os.path.join(PROJECT_ROOT, "modules")
if MODULES_DIR not in sys.path:
    sys.path.append(MODULES_DIR)

from parapara_pdf2json import extract_paragraphs
from parapara_tagging_by_structure import structure_tagging
from parapara_json2html import json2html


def _resolve_pdf_path(path_value: str) -> str:
    if not path_value:
        raise ValueError("PDF path is required")
    pdf_path = os.path.abspath(path_value)
    if not pdf_path.lower().endswith(".pdf"):
        raise ValueError(f"Not a PDF: {pdf_path}")
    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    return pdf_path


def _remove_if_exists(path_value: str) -> None:
    if os.path.exists(path_value):
        os.remove(path_value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run extraction test on a PDF.")
    parser.add_argument(
        "--pdf",
        default=os.path.join("data", "sandbox", "trpg_sample.pdf"),
        help="Path to the PDF to process.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing JSON/HTML outputs if present.",
    )
    parser.add_argument(
        "--skip-tagging",
        action="store_true",
        help="Skip structure tagging step.",
    )
    parser.add_argument(
        "--skip-html",
        action="store_true",
        help="Skip HTML export step.",
    )

    args = parser.parse_args()

    pdf_path = _resolve_pdf_path(args.pdf)
    json_path = os.path.splitext(pdf_path)[0] + ".json"
    html_path = os.path.splitext(pdf_path)[0] + ".html"

    if os.path.exists(json_path) and not args.force:
        print(f"JSON already exists: {json_path}")
        print("Use --force to overwrite.")
        return 1

    if args.force:
        _remove_if_exists(json_path)
        _remove_if_exists(html_path)

    os.makedirs(os.path.dirname(json_path), exist_ok=True)

    print("Extracting paragraphs...")
    extract_paragraphs(pdf_path, json_path)

    if not args.skip_tagging:
        symbol_font_path = os.path.join(PROJECT_ROOT, "config", "symbolfonts.txt")
        print("Running structure tagging...")
        structure_tagging(json_path, symbol_font_path)

    if not args.skip_html:
        print("Exporting HTML...")
        json2html(json_path)

    print("Done")
    print(f"JSON: {json_path}")
    if not args.skip_html:
        print(f"HTML: {html_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
