"""CLI: build the bilingual review workbook for the fact templates (BENCHMARK_SPEC.md §7.4).

Reviewers check each relation's patterns, each value's three surface forms, and each
person's possessive forms, instead of reading every rendered fact. The workbook is
generated from data/templates/, so regenerate it after any template fix.

Writes .xlsx with the standard library only (an .xlsx file is zipped XML).
"""

from __future__ import annotations

import argparse
import logging
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import yaml

from xlmem.benchmark.templates import load_and_render, possessive

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("review_sheet")

DOMAINS = ["dining", "work", "travel", "family", "finance", "hobbies", "tech"]
PATTERNS = [
    ("statement", "Statement (plant turn)"),
    ("probe", "Question (probe)"),
    ("correction", "Correction turn"),
    ("reprobe", "Question after correction"),
]
VERDICT = ["Verdict (OK / Fix)", "Suggested fix", "Comment"]

# Items the author was unsure about. Everything else still needs a check.
NOTES: dict[tuple[str, str], str] = {
    ("payment_method", "statement"): "Two का in a row ('मेरी पत्नी का पेमेंट का पसंदीदा तरीका') is "
     "grammatical, as in other relations (खेलने का पसंदीदा खेल), but is it natural? Alternatives: "
     "'पेमेंट करने का मेरा पसंदीदा तरीका', 'पसंदीदा पेमेंट मोड'.",
    ("commute_mode", "statement"): "Hinglish 'commute ka mode' may sound stiff. Batch 2 values: "
     "Hinglish uses 'auto' and 'cycle' (shortened).",
    ("dream_country", "statement"): "Is 'मेरा सपनों का देश' natural for 'my dream country'? "
     "Batch 2 value: Egypt is मिस्र in Hindi but 'Egypt' in Hinglish.",
    ("shift_start", "statement"): "Time format: 'सुबह 9 बजे' vs '9 बजे सुबह'.",
    ("alma_mater", "statement"): "Past tense (था/tha) used throughout this relation.",
    # Batch 2
    ("favorite_cuisine", "statement"): "Hindi uses भोजन शैली (f), not पसंदीदा खाना, because "
     "खाना ('food') overlaps favorite_dish's पकवान and the user, mother and brother have both "
     "facts: the probes must not be answerable by the other fact. Is भोजन शैली natural? "
     "Any alternative must stay distinct from पकवान. Hinglish 'cuisine' taken as f.",
    ("department", "statement"): "Loanword डिपार्टमेंट used; would विभाग be more natural?",
    ("main_investment", "probe"): "Is 'किसमें है?' natural for 'what is ... invested in?'",
    ("favorite_instrument", "statement"): "वाद्ययंत्र vs साज़: which is more natural?",
    ("home_city", "statement"): "New values: is मैसूर (vs मैसूरु) the right Hindi form?",
}

PEOPLE_NOTES = {
    "user_friend": "Hindi 'मेरे दोस्त' / Hinglish 'mere friend' present the friend as male; "
    "English 'my friend's' is gender-neutral. Acceptable, or use a fixed-gender person?",
    "user_father": "The health batch uses 'मेरे पिता' (f_101_dist); the templates use "
    "'मेरे पिताजी'. Keep both, or align?",
}

EXISTING_DATA_ISSUES = [
    # PROPOSAL, not an approved policy (open decision E, docs/review/FACT_BANK_DECISIONS.md):
    # keep data/facts_v1.yaml frozen, because it is the pilot runs' input and its sha256 is
    # in runs/pilot_v2/manifest/, and apply agreed fixes in the next fact-bank version.
    # Until decided, the rows below only propose corrections; facts_v1.yaml is unchanged.
    ("facts_v1.yaml", "f_010", "Grammar: 'मेरी अगली महीने मनाली जाने की योजना है।' "
     "Proposed: 'अगले महीने मेरी मनाली जाने की योजना है।' (महीना is m: अगले महीने)."),
    ("facts_v1.yaml", "f_006", "Question drops 'morning', which the fact needs ('favorite "
     "MORNING beverage'), and the Hindi has a gender error ('मेरी पसंदीदा पेय': पेय is m). "
     "Proposed: en 'What is my favorite morning beverage?', hi 'सुबह की मेरी पसंदीदा ड्रिंक "
     "क्या है?' (ड्रिंक as in the statement), hi-en 'Meri favorite morning beverage kya hai?' "
     "(matches the statement's 'Meri')."),
    ("facts_v1.yaml, health_batch_01.yaml",
     "f_002, f_003, f_004, f_008, f_009, f_012, f_017; f_103, f_104, f_104_dist, f_106, "
     "f_109, f_110",
     "First-person verbs are masculine ('रहता हूँ', 'karta hoon'). Grammatical for a male "
     "speaker (BENCHMARK_SPEC §7.2 uses 'मैं पुणे में रहता हूँ'), so this is a speaker-persona "
     "question, not an error. The templates avoid first-person verbs entirely. Decide: "
     "document a male speaker, or rewrite these without speaker gender."),
    ("health_batch_01.yaml, facts_v1.yaml", "f_104, f_104_dist, f_012",
     "Overlapping diet facts for the user. f_104_dist (vegetarian, 'I am also vegetarian') "
     "restates f_012 (vegetarian, 'I follow a strictly vegetarian diet') under another "
     "relation name. f_104's question 'What kind of diet do I follow?' is also answered by "
     "f_012; both are base facts, so both are asked. (f_104_dist shares f_104's question, "
     "as a value-shift distractor does, but distractors are never asked.) Needs a decision "
     "(docs/review/FACT_BANK_DECISIONS.md, item A); not changed here."),
    ("facts_v1.yaml", "f_004", "domain is 'languages', which is not one of the 8 approved "
     "domains (BENCHMARK_SPEC §3). Which domain should it count under?"),
    ("health_batch_01.yaml", "f_105, f_109, f_110",
     "Value keys (flu_shot_pending, regular_donor, yoga_daily) are abstract labels that "
     "occur in none of the sentences, and hand-written facts have no value_aliases. Today "
     "strict matching can credit them only when a memory contains a whole authored sentence "
     "verbatim; a paraphrase never matches. Which aliases are authorized is decision D1."),
]

INSTRUCTIONS = [
    "XLMem fact templates: bilingual review (BENCHMARK_SPEC.md §7.4)",
    "",
    "Every benchmark fact is generated from the patterns and word lists in this workbook, "
    "so fixing a row here fixes every fact that uses it.",
    "Check that English, Hindi and Hinglish say exactly the same thing, read naturally, "
    "and use correct grammar and gender agreement.",
    "Hinglish follows BENCHMARK_SPEC.md §6: Hindi word order and grammar words "
    "(ka/ki/ke, hai, mein), English content words, Latin script.",
    "",
    "Tabs:",
    "Patterns: one row per sentence pattern. {poss} is the person ('my', 'my mother's'); "
    "{v}, {old}, {new} are values. The Example column shows a real rendered fact.",
    "Values: each value in its three forms. The Hindi form must be what a speaker would "
    "write; the Hinglish form is what they would type in Latin script.",
    "People: the possessive forms for each person. Hindi and Hinglish agree with the "
    "gender of the following noun (masculine / feminine / plural-honorific-oblique).",
    "Hand-written facts: facts written before the templates (data/facts_v1.yaml, the "
    "health batch). Check each sentence directly.",
    "Existing data: problems found in the facts written before the templates.",
    "",
    "In each row, set Verdict to OK or Fix. For Fix, write the corrected text in "
    "'Suggested fix'. Use Comment for anything else.",
    "Please review independently: two reviewers, two separate copies of this file.",
]


def _col(n: int) -> str:
    letters = ""
    while n:
        n, r = divmod(n - 1, 26)
        letters = chr(65 + r) + letters
    return letters


def _sheet_xml(rows: list[list[str]], widths: list[int], verdict_col: int | None) -> str:
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
           '<sheetViews><sheetView workbookViewId="0">'
           '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
           '</sheetView></sheetViews>', "<cols>"]
    out += [f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
            for i, w in enumerate(widths, start=1)]
    out += ["</cols>", "<sheetData>"]
    for r, row in enumerate(rows, start=1):
        style = ' s="1"' if r == 1 else ""
        cells = "".join(
            f'<c r="{_col(c)}{r}" t="inlineStr"{style}><is><t xml:space="preserve">'
            f"{escape(value)}</t></is></c>"
            for c, value in enumerate(row, start=1)
            if value
        )
        out.append(f'<row r="{r}">{cells}</row>')
    out.append("</sheetData>")
    if len(rows) > 1:
        out.append(f'<autoFilter ref="A1:{_col(len(rows[0]))}{len(rows)}"/>')
    if verdict_col is not None and len(rows) > 1:
        ref = f"{_col(verdict_col)}2:{_col(verdict_col)}{len(rows)}"
        out.append('<dataValidations count="1"><dataValidation type="list" allowBlank="1" '
                   f'sqref="{ref}"><formula1>"OK,Fix"</formula1></dataValidation>'
                   "</dataValidations>")
    out.append("</worksheet>")
    return "".join(out)


_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="3"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFE3EAF2"/><bgColor indexed="64"/>'
    "</patternFill></fill></fills>"
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="2">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
    '<alignment vertical="top" wrapText="1"/></xf>'
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" '
    'applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    "</styleSheet>"
)


Sheet = tuple[str, list[list[str]], list[int], int | None]


def write_xlsx(path: Path, sheets: list[Sheet]) -> None:
    """Write sheets as (name, rows, column widths, 1-based verdict column or None)."""
    ns = "http://schemas.openxmlformats.org"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   f'<Types xmlns="{ns}/package/2006/content-types">'
                   '<Default Extension="rels" '
                   'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/'
                   'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/'
                   'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                             'ContentType="application/vnd.openxmlformats-officedocument.'
                             'spreadsheetml.worksheet+xml"/>'
                             for i in range(1, len(sheets) + 1))
                   + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   f'<Relationships xmlns="{ns}/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
                   'officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   "</Relationships>")
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   f'<workbook xmlns="{ns}/spreadsheetml/2006/main" '
                   f'xmlns:r="{ns}/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
                             for i, (name, *_rest) in enumerate(sheets, start=1))
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   f'<Relationships xmlns="{ns}/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i}" Type="{ns}/officeDocument/2006/'
                             f'relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                             for i in range(1, len(sheets) + 1))
                   + f'<Relationship Id="rId{len(sheets) + 1}" Type="{ns}/officeDocument/'
                   '2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr("xl/styles.xml", _STYLES)
        for i, (_name, rows, widths, verdict_col) in enumerate(sheets, start=1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(rows, widths, verdict_col))


def _example(facts: list[dict[str, Any]], relation: str, pattern: str) -> str:
    """One rendered fact for this relation, preferring a non-user entity (shows agreement)."""
    candidates = [f for f in facts if f["relation"] == relation]
    if pattern in ("correction", "reprobe"):
        candidates = [f for f in candidates if f["update"]]
        if not candidates:
            return "(no fact in this batch uses a correction)"
    candidates.sort(key=lambda f: f["entity"] == "user")
    f = candidates[0]
    block = {
        "statement": f["surface"],
        "probe": f["probe_questions"],
        "correction": (f["update"] or {}).get("surface", {}),
        "reprobe": (f["update"] or {}).get("probe_questions", {}),
    }[pattern]
    lines = [block[lang] for lang in ("en", "hi", "hi-en") if lang in block]
    return "\n".join([f["id"], *lines])


# Facts not generated from templates; reviewers check their sentences one by one.
HAND_WRITTEN = ("data/facts_v1.yaml", "data/candidates/health_batch_01.yaml")


def _hand_written_rows(root: Path) -> list[list[str]]:
    rows = [["ID", "File", "Fact", "Sentence", "English", "Hindi", "Hinglish", *VERDICT]]
    for rel in HAND_WRITTEN:
        with open(root / rel, encoding="utf-8") as f:
            facts = (yaml.safe_load(f) or {}).get("facts", [])
        for fact in facts:
            update = fact.get("update") or {}
            blocks = [("Statement", fact.get("surface") or {}),
                      ("Question", fact.get("probe_questions") or {}),
                      ("Correction", update.get("surface") or {}),
                      ("Question after correction", update.get("probe_questions") or {})]
            for label, block in blocks:
                if block:
                    rows.append([f"H{len(rows):03d}", Path(rel).name, str(fact["id"]), label,
                                 block.get("en", ""), block.get("hi", ""),
                                 block.get("hi-en", "(not used)")])
    return rows


def build_sheets(templates_dir: Path, entities_path: Path) -> list[Sheet]:
    """Rows for each review tab, built from the domain templates and entity lexicon."""
    with open(entities_path, encoding="utf-8") as f:
        entities = yaml.safe_load(f)["entities"]

    patterns = [["ID", "Domain", "Relation", "Pattern", "Hindi noun gender",
                 "Hinglish noun gender", "English", "Hindi", "Hinglish", "Example (rendered)",
                 "Author's note", *VERDICT]]
    values = [["ID", "Domain", "Relation", "Value key", "English", "Hindi", "Hinglish",
               "Used by facts", *VERDICT]]
    for domain in DOMAINS:
        path = templates_dir / f"{domain}.yaml"
        with open(path, encoding="utf-8") as f:
            template = yaml.safe_load(f)
        facts = load_and_render(path, entities_path)
        for relation, spec in template["relations"].items():
            gender = spec["gender"]
            mismatch = gender["hi"] != gender["hi-en"]
            for key, label in PATTERNS:
                note = NOTES.get((relation, key), "")
                if key == "statement" and mismatch:
                    note = (note + " " if note else "") + (
                        "Hindi and Hinglish nouns differ in gender here: check the Hinglish one."
                    )
                texts = spec[key]
                patterns.append([
                    f"P{len(patterns):03d}", domain, relation, label,
                    gender["hi"] if key == "statement" else "",
                    gender["hi-en"] if key == "statement" else "",
                    texts.get("en", ""), texts.get("hi", ""),
                    texts.get("hi-en", "(not used: re-probes are asked in en or hi)"),
                    _example(facts, relation, key), note,
                ])
            for value, forms in spec["values"].items():
                used = [
                    f["id"]
                    for f in facts
                    if f["relation"] == relation
                    and value in (f["value"], (f["update"] or {}).get("updated_value"))
                ]
                values.append([f"V{len(values):03d}", domain, relation, value, forms["en"],
                               forms["hi"], forms["hi-en"], ", ".join(used) or "(spare)"])

    people = [["ID", "Person", "English", "Hindi (m / f / plural-oblique)",
               "Hinglish (m / f / plural-oblique)", "Author's note", *VERDICT]]
    for name, e in entities.items():
        people.append([
            f"E{len(people):03d}", name, possessive(e, "en", ""),
            " / ".join(possessive(e, "hi", g) for g in ("m", "f", "p")),
            " / ".join(possessive(e, "hi-en", g) for g in ("m", "f", "p")),
            PEOPLE_NOTES.get(name, ""),
        ])

    existing = [["ID", "File", "Facts", "Issue", *VERDICT]]
    for file, ids, issue in EXISTING_DATA_ISSUES:
        existing.append([f"X{len(existing):03d}", file, ids, issue])

    return [
        ("How to review", [[line] for line in INSTRUCTIONS], [120], None),
        ("Patterns", patterns, [7, 9, 20, 18, 9, 9, 34, 34, 34, 44, 30, 11, 30, 30], 12),
        ("Values", values, [7, 9, 20, 20, 22, 22, 22, 22, 11, 30, 30], 9),
        ("People", people, [7, 14, 26, 40, 40, 34, 11, 30, 30], 7),
        ("Hand-written facts", _hand_written_rows(templates_dir.parent.parent),
         [7, 18, 11, 18, 40, 40, 40, 11, 30, 30], 8),
        ("Existing data", existing, [7, 20, 26, 70, 11, 30, 30], 5),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the bilingual review workbook.")
    parser.add_argument("--templates", default="data/templates")
    parser.add_argument("--out", default="docs/review/fact_templates_review.xlsx")
    args = parser.parse_args()

    out = Path(args.out)
    if out.exists():
        logger.error("Refusing to overwrite %s; delete it first if regenerating is intended.", out)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    templates = Path(args.templates)
    sheets = build_sheets(templates, templates / "entities.yaml")
    write_xlsx(out, sheets)
    counts = ", ".join(f"{name}: {len(rows) - 1}" for name, rows, *_ in sheets[1:])
    logger.info("Wrote %s (%s rows to review)", out, counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
