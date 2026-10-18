"""Review workbook generation (xlmem/scripts/review_sheet.py)."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from xlmem.scripts.review_sheet import build_sheets, write_xlsx

ROOT = Path(__file__).parent.parent
TEMPLATES = ROOT / "data" / "templates"


def test_workbook_covers_every_relation_value_and_person(tmp_path: Path) -> None:
    sheets = {name: rows for name, rows, *_ in build_sheets(TEMPLATES, TEMPLATES / "entities.yaml")}
    patterns, values, people = sheets["Patterns"], sheets["Values"], sheets["People"]

    relations = {row[2] for row in patterns[1:]}
    assert len(patterns) - 1 == 4 * len(relations)  # statement, probe, correction, re-probe
    assert len(people) - 1 == 13
    assert all(row[-1] for row in values[1:])  # every value says which facts use it
    hand = sheets["Hand-written facts"]
    assert {row[2] for row in hand[1:]} >= {"f_001", "f_017", "f_101"}  # facts_v1 + health
    first_person = people[1]
    assert first_person[3] == "मेरा / मेरी / मेरे"


def test_written_xlsx_is_well_formed_with_verdict_dropdown(tmp_path: Path) -> None:
    out = tmp_path / "review.xlsx"
    write_xlsx(out, build_sheets(TEMPLATES, TEMPLATES / "entities.yaml"))
    with zipfile.ZipFile(out) as z:
        workbook = z.read("xl/workbook.xml").decode()
        assert re.findall(r'<sheet name="([^"]+)"', workbook) == [
            "How to review", "Patterns", "Values", "People", "Hand-written facts",
            "Existing data",
        ]
        patterns = z.read("xl/worksheets/sheet2.xml").decode()
        assert '<formula1>"OK,Fix"</formula1>' in patterns
        assert "पसंदीदा पकवान" in patterns
