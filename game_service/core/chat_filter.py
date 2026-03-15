"""
Safe Chat Filter — PHI/PII Prevention Engine

Before any chat message is written to Redis or broadcast to other players,
it passes through this synchronous filter. If PHI or toxicity is detected,
the message is permanently rejected and never stored.

Two-layer approach:
  1. Regex patterns: fast, deterministic detection of known PHI patterns
     (blood pressure readings, glucose values, drug names, etc.)
  2. Drug name blocklist: common chronic-disease medications
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ─── PHI Regex Patterns ───────────────────────────────────────────────────────

_PHI_PATTERNS: list[tuple[str, re.Pattern]] = [
    # Blood pressure: "120/80", "125/85 mmHg"
    ("blood_pressure", re.compile(r"\b\d{2,3}/\d{2,3}(\s*mmhg)?\b", re.IGNORECASE)),

    # A1C percentage: "A1C 7.2%", "HbA1c of 6.8"
    ("a1c", re.compile(r"\b(a1c|hba1c)\s*(of\s*)?\d+(\.\d+)?%?\b", re.IGNORECASE)),

    # Glucose values: "250 mg/dL", "14 mmol/L", "glucose is 180"
    ("glucose_value", re.compile(
        r"\b(glucose|bg|blood sugar)\s*(is|of|was|reading)?\s*\d+(\.\d+)?\s*(mg/dl|mmol/l|mg)?\b",
        re.IGNORECASE
    )),

    # Raw numeric glucose (very high/low values that are clearly medical)
    ("glucose_numeric", re.compile(r"\b(4[0-9]|[5-9]\d|[1-9]\d{2,3})\s*(mg/dl|mmol)\b", re.IGNORECASE)),

    # Heart rate with bpm context
    ("heart_rate", re.compile(r"\b(heart rate|hr|pulse)\s*(is|of|was)?\s*\d+\s*(bpm)?\b", re.IGNORECASE)),

    # Weight with unit context
    ("weight", re.compile(r"\b(weigh(t|s|ed)|bmi)\s*(is|of|was)?\s*\d+(\.\d+)?\s*(kg|lbs?|pounds?)?\b", re.IGNORECASE)),

    # Insulin dose: "10 units", "took 5u of insulin"
    ("insulin_dose", re.compile(r"\b\d+\s*(units?|u)\s*(of\s*)?(insulin|basal|bolus|novolog|humalog|levemir|lantus)?\b", re.IGNORECASE)),
]

# ─── Drug Name Blocklist ──────────────────────────────────────────────────────

_DRUG_NAMES: set[str] = {
    # Diabetes medications
    "metformin", "insulin", "ozempic", "wegovy", "trulicity", "victoza",
    "jardiance", "farxiga", "invokana", "januvia", "tradjenta", "onglyza",
    "novolog", "humalog", "lantus", "levemir", "toujeo", "tresiba",
    "basaglar", "admelog", "fiasp",
    # PCOS / hormonal
    "spironolactone", "clomid", "letrozole", "progesterone",
    # Hypertension
    "lisinopril", "amlodipine", "losartan", "metoprolol", "atenolol",
    "hydrochlorothiazide", "ramipril", "valsartan",
    # ADHD / mental health (often comorbid with chronic illness)
    "adderall", "ritalin", "vyvanse", "concerta", "strattera",
    "sertraline", "fluoxetine", "escitalopram", "bupropion", "wellbutrin",
    # Thyroid
    "levothyroxine", "synthroid", "cytomel",
    # Other chronic
    "prednisone", "hydroxychloroquine", "azathioprine",
}

_DRUG_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(d) for d in _DRUG_NAMES) + r")\b",
    re.IGNORECASE,
)

# ─── Severe Toxicity Patterns (brief list for MVP) ────────────────────────────

_TOXICITY_PATTERNS = [
    re.compile(r"\b(kill yourself|kys|go die)\b", re.IGNORECASE),
]


@dataclass
class FilterResult:
    allowed: bool
    reason: str = ""
    category: str = ""  # "phi_pattern", "drug_name", "toxicity", or ""


def filter_message(text: str) -> FilterResult:
    """
    Returns FilterResult. If allowed=False, the message must be permanently
    dropped and the API must return 403 with a localized privacy warning.
    """
    # PHI patterns
    for category, pattern in _PHI_PATTERNS:
        if pattern.search(text):
            return FilterResult(
                allowed=False,
                reason="Message contains health metric data.",
                category="phi_pattern",
            )

    # Drug name blocklist
    if _DRUG_PATTERN.search(text):
        return FilterResult(
            allowed=False,
            reason="Message contains medication or drug references.",
            category="drug_name",
        )

    # Toxicity
    for pattern in _TOXICITY_PATTERNS:
        if pattern.search(text):
            return FilterResult(
                allowed=False,
                reason="Message contains harmful content.",
                category="toxicity",
            )

    return FilterResult(allowed=True)
