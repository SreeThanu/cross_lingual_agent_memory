"""Strict and Lenient (NLI) matching algorithms for memory scoring."""

from __future__ import annotations

import logging
import unicodedata
from typing import Sequence

logger = logging.getLogger(__name__)


_NUKTA = "\u093c"


def normalize_text(text: str) -> str:
    """Lowercase, NFC-normalize, fold the Devanagari nukta, and replace punctuation with spaces.

    Combining marks (Unicode category M: Devanagari vowel signs, virama, anusvara)
    are kept. Python's \\w does not match them, so a \\w-based filter turns
    "पुणे" into "प ण". The nukta is dropped so फ़िल्टर and फिल्टर compare equal.
    """
    text = unicodedata.normalize("NFC", text.lower()).replace(_NUKTA, "")
    kept = (ch if ch.isspace() or unicodedata.category(ch)[0] in "LNM" else " " for ch in text)
    return " ".join("".join(kept).split())


def strict_match(target_value: str, candidate_text: str, aliases: Sequence[str] = ()) -> bool:
    """Strict evaluation: checks whether target_value or any alias is present in candidate_text.

    Args:
        target_value: Canonical target string.
        candidate_text: Text from memory record or model output.
        aliases: Optional list of alternate surface values.

    Returns:
        True if exact match found after normalization.
    """
    norm_candidate = normalize_text(candidate_text)
    targets = [target_value] + list(aliases)

    expanded_targets: list[str] = []
    for t in targets:
        norm_target = normalize_text(t)
        if not norm_target:
            continue
        expanded_targets.append(norm_target)
        if norm_target.endswith("s") and len(norm_target) > 3:
            expanded_targets.append(norm_target[:-1])
        elif len(norm_target) > 2:
            expanded_targets.append(norm_target + "s")

    # Whole-token match on the normalized, single-space-joined text. (\\b fails
    # around Devanagari combining marks, and a bare substring test matches
    # "visa" inside "advisable".)
    padded_candidate = f" {norm_candidate} "
    return any(f" {target} " in padded_candidate for target in expanded_targets)


class NLIJudge:
    """Lenient evaluator using a multilingual NLI model (e.g. mDeBERTa-v3-base-xnli)."""

    def __init__(
        self,
        model_name: str = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7",
        threshold: float = 0.70,
        mock_mode: bool = False,
    ) -> None:
        self.model_name = model_name
        self.threshold = threshold
        self.mock_mode = mock_mode
        self._pipeline = None

        if not self.mock_mode:
            self._init_pipeline()

    def _init_pipeline(self) -> None:
        try:
            from transformers import pipeline
            import torch

            device = 0 if torch.cuda.is_available() else -1
            self._pipeline = pipeline(
                "zero-shot-classification",
                model=self.model_name,
                device=device,
            )
            logger.info("Initialized NLI judge with '%s' on device %s", self.model_name, device)
        except Exception as e:
            logger.warning(
                "Could not initialize NLI pipeline (%s). Falling back to mock/heuristic mode: %s",
                self.model_name,
                e,
            )
            self.mock_mode = True

    def is_entailed(self, premise: str, hypothesis: str) -> bool:
        """Check whether the premise entails the hypothesis.

        Args:
            premise: Text from memory record or agent response.
            hypothesis: Templated declarative statement of the ground truth fact.

        Returns:
            True if entailment score >= threshold.
        """
        if not premise.strip() or not hypothesis.strip():
            return False

        if self.mock_mode or self._pipeline is None:
            # Fallback heuristic: token overlap between premise and hypothesis
            p_words = set(normalize_text(premise).split())
            h_words = set(normalize_text(hypothesis).split())
            if not h_words:
                return False
            overlap = len(p_words.intersection(h_words)) / len(h_words)
            return overlap >= 0.50

        # "{}" passes the fact sentence through verbatim; the pipeline default
        # ("This example is {}.") would wrap it into an ungrammatical hypothesis.
        res = self._pipeline(premise, candidate_labels=[hypothesis], hypothesis_template="{}")
        scores = res.get("scores", [0.0])
        return bool(scores[0] >= self.threshold)
