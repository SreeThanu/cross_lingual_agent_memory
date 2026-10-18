"""Render template-authored facts (BENCHMARK_SPEC.md Sections 2 and 4) from a domain template.

Deterministic string substitution over a reviewed template + value lexicon: no
model calls, no randomness. Bilingual reviewers check one template per relation
and one row per value, rather than every rendered sentence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_HI_AGREEMENT = {"m": "ा", "f": "ी"}
_HIEN_AGREEMENT = {"m": "a", "f": "i"}
SURFACE_LANGS = ("en", "hi", "hi-en")
REPROBE_LANGS = ("en", "hi")


class TemplateError(ValueError):
    """A template or fact plan violates the benchmark construction rules."""


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


def possessive(entity: dict[str, str], lang: str, gender: str) -> str:
    """Possessor phrase for `entity` in `lang`, agreeing with a head noun of `gender`."""
    if lang == "en":
        return entity["poss_en"]
    if lang == "hi":
        return entity["poss_hi_stem"] + _HI_AGREEMENT[gender]
    if lang == "hi-en":
        return entity["poss_hien_stem"] + _HIEN_AGREEMENT[gender]
    raise TemplateError(f"unknown language {lang!r}")


def _fill(template: str, poss: str, **slots: str) -> str:
    return template.format(poss=poss, Poss=_capitalize(poss), **slots)


def _value_aliases(forms: dict[str, str]) -> dict[str, list[str]]:
    """Hindi form of the value, plus its Hinglish form when that differs from English
    (e.g. "karela" vs "bitter gourd"). Both occur verbatim in the rendered surfaces."""
    aliases = {"hi": [forms["hi"]]}
    if forms["hi-en"].lower() != forms["en"].lower():
        aliases["translit"] = [forms["hi-en"]]
    return aliases


def render_fact(
    relation_name: str,
    relation: dict[str, Any],
    entity_name: str,
    entity: dict[str, str],
    value: str,
    domain: str,
    fact_id: str,
    distractor_of: str | None = None,
    updated_value: str | None = None,
) -> dict[str, Any]:
    """Render one fact in the fact-bank schema."""
    values = relation["values"]
    for v in (value, updated_value):
        if v is not None and v not in values:
            raise TemplateError(f"{fact_id}: value {v!r} not in {relation_name} lexicon")

    gender = relation["gender"]
    # English possessives do not inflect, so templates give a gender for hi and hi-en only.
    poss = {lang: possessive(entity, lang, gender.get(lang, "")) for lang in SURFACE_LANGS}
    forms = values[value]

    fact: dict[str, Any] = {
        "id": fact_id,
        "domain": domain,
        "entity": entity_name,
        "relation": relation_name,
        "value": value,
        "value_aliases": _value_aliases(forms),
        "distractor_of": distractor_of,
        "surface": {
            lang: _fill(relation["statement"][lang], poss[lang], v=forms[lang])
            for lang in SURFACE_LANGS
        },
        "probe_questions": {
            lang: _fill(relation["probe"][lang], poss[lang]) for lang in SURFACE_LANGS
        },
        "update": None,
    }

    if updated_value is not None:
        new_forms = values[updated_value]
        fact["update"] = {
            "updated_value": updated_value,
            "surface": {
                lang: _fill(
                    relation["correction"][lang], poss[lang], old=forms[lang], new=new_forms[lang]
                )
                for lang in SURFACE_LANGS
            },
            "probe_questions": {
                lang: _fill(relation["reprobe"][lang], poss[lang]) for lang in REPROBE_LANGS
            },
        }
    return fact


def render_domain(
    template: dict[str, Any], entities: dict[str, dict[str, str]]
) -> list[dict[str, Any]]:
    """Render every fact in a domain template's plan, enforcing the construction rules:

    - every (entity, relation) pair is unique, so each slot has one ground-truth value;
    - base values are unique within a relation, and corrected values never coincide
      with a planted value (no accidental, unlabelled near misses);
    - a distractor is an entity-shift of its base fact (BENCHMARK_SPEC.md Section 4).
    """
    domain = template["domain"]
    relations = template["relations"]
    plan = template["facts"]
    base_by_id = {p["id"]: p for p in plan if "distractor_of" not in p}

    slots: set[tuple[str, str]] = set()
    planted_values: dict[str, set[str]] = {}
    corrected_values: dict[str, set[str]] = {}
    facts: list[dict[str, Any]] = []

    for p in plan:
        fid = p["id"]
        base = base_by_id.get(p["distractor_of"]) if "distractor_of" in p else p
        if base is None:
            raise TemplateError(f"{fid}: distractor_of {p['distractor_of']!r} is not a base fact")
        relation_name = base["relation"]
        if relation_name not in relations:
            raise TemplateError(f"{fid}: unknown relation {relation_name!r}")
        entity_name = p["entity"]
        if entity_name not in entities:
            raise TemplateError(f"{fid}: unknown entity {entity_name!r}")

        slot = (entity_name, relation_name)
        if slot in slots:
            raise TemplateError(f"{fid}: duplicate (entity, relation) slot {slot}")
        slots.add(slot)

        is_distractor = p is not base
        if is_distractor:
            if "value" in p or "update" in p:
                raise TemplateError(f"{fid}: entity-shift distractor inherits its base value")
            value, updated = base["value"], None
        else:
            value, updated = p["value"], p.get("update")
            if value in planted_values.setdefault(relation_name, set()):
                raise TemplateError(f"{fid}: value {value!r} already planted for {relation_name}")
            planted_values[relation_name].add(value)
            if updated is not None:
                corrected_values.setdefault(relation_name, set()).add(updated)

        facts.append(
            render_fact(
                relation_name,
                relations[relation_name],
                entity_name,
                entities[entity_name],
                value,
                domain,
                fid,
                distractor_of=p.get("distractor_of"),
                updated_value=updated,
            )
        )

    for relation_name, corrected in corrected_values.items():
        clash = corrected & planted_values.get(relation_name, set())
        if clash:
            raise TemplateError(
                f"{relation_name}: corrected value(s) {sorted(clash)} are also planted values"
            )
    return facts


def load_and_render(template_path: str | Path, entities_path: str | Path) -> list[dict[str, Any]]:
    """Load a domain template and the entity lexicon from YAML and render the fact plan."""
    with open(template_path, encoding="utf-8") as f:
        template = yaml.safe_load(f)
    with open(entities_path, encoding="utf-8") as f:
        entities = yaml.safe_load(f)["entities"]
    return render_domain(template, entities)
