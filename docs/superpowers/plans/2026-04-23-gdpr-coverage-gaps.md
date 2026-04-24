# GDPR Coverage Gaps — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close three GDPR regex gaps (French driver's license, French NIF tax ID, URL) and add the missing Article 9 special category (trade union membership) as a zero-shot NER label.

**Architecture:** Each regex gap gets a `Pattern` object following the existing `_base.Pattern` dataclass convention. New patterns are added to `national_id.py` (national identifiers) or a new `url.py` (online identifiers). All are wired into `DEFAULT_PATTERNS` in `__init__.py` with ordering comments that explain any Luhn-overlap reasoning. The NER label is added to `LABEL_MAP` in the smoke test script and to the production `config.toml` labels list; GLiNER2 is zero-shot so no retraining is needed.

**Tech Stack:** Python 3.11+, `re`, `pytest`, `piighost.detector.patterns._base.Pattern`, `piighost.detector.patterns.__init__.DEFAULT_PATTERNS`

---

## File map

| Action | File |
|---|---|
| Modify | `src/piighost/detector/patterns/national_id.py` |
| Modify | `src/piighost/detector/patterns/__init__.py` |
| Create | `src/piighost/detector/patterns/url.py` |
| Modify | `tests/unit/detector/patterns/test_national_id.py` |
| Create | `tests/unit/detector/patterns/test_url.py` |
| Modify | `scripts/test_french_model.py` |
| Modify | `.piighost/config.toml` |

---

## Task 1: FR_PERMIS_CONDUIRE and FR_NIF patterns

**Files:**
- Modify: `tests/unit/detector/patterns/test_national_id.py`
- Modify: `src/piighost/detector/patterns/national_id.py`

### Background

**FR_PERMIS_CONDUIRE** — French EU-harmonised driving licence number.  
Format: 2 digits + 2 uppercase letters + 6 digits = 10 characters, e.g. `07AB123456`.  
This is deliberately distinct from the passport biometric format already in the codebase:
- passport biometric: `\d{2}[A-Z]{2}\d{5}` (9 chars — 5 trailing digits)
- driving licence:    `\d{2}[A-Z]{2}\d{6}` (10 chars — 6 trailing digits)

No public checksum algorithm exists for DL numbers, so no validator.

**FR_NIF** — French individual tax identifier (numéro fiscal / SPI), 13 digits, e.g. `1234567890123`.  
Must be ordered before `CREDIT_CARD` in `DEFAULT_PATTERNS` (old 13-digit Visa cards also pass Luhn; in French legal documents a 13-digit number is almost always a tax ID, never a payment card).  
No checksum to validate (the algorithm is not public).

---

- [ ] **Step 1: Write the failing tests**

The test file already exists. Replace **only the import block at the top** (lines 1-4) with the expanded version below, then **append the new test functions** after the last existing test.

New import block (replaces lines 1-4):

```python
from piighost.detector.patterns.national_id import (
    FR_NIR_PATTERN,
    DE_PERSONALAUSWEIS_PATTERN,
    FR_SIRET_PATTERN,
    FR_PASSPORT_PATTERN,
    FR_PERMIS_CONDUIRE_PATTERN,
    FR_NIF_PATTERN,
)
```

New test functions (append after line 37, the last existing test):

```python
# ── FR_PERMIS_CONDUIRE ────────────────────────────────────────────────────────

def test_fr_permis_conduire_matches():
    m = FR_PERMIS_CONDUIRE_PATTERN.regex.search("permis no 07AB123456 valide")
    assert m is not None
    assert m.group(0) == "07AB123456"


def test_fr_permis_conduire_rejects_passport_biometric():
    # passport biometric has 5 trailing digits; DL requires 6 → no match
    m = FR_PERMIS_CONDUIRE_PATTERN.regex.search("09AA12345")
    assert m is None


def test_fr_permis_conduire_rejects_bare_letters():
    m = FR_PERMIS_CONDUIRE_PATTERN.regex.search("ABCDEFGHIJ")
    assert m is None


def test_fr_permis_conduire_label():
    assert FR_PERMIS_CONDUIRE_PATTERN.label == "FR_PERMIS_CONDUIRE"


def test_fr_permis_conduire_confidence():
    assert FR_PERMIS_CONDUIRE_PATTERN.confidence == 0.99


# ── FR_NIF ────────────────────────────────────────────────────────────────────

def test_fr_nif_matches_13_digits():
    m = FR_NIF_PATTERN.regex.search("NIF 1234567890123 fiscal")
    assert m is not None
    assert m.group(0) == "1234567890123"


def test_fr_nif_rejects_14_digits():
    # 14 digits → SIRET territory; word boundary prevents match
    m = FR_NIF_PATTERN.regex.search("55204944776279")
    assert m is None


def test_fr_nif_rejects_12_digits():
    m = FR_NIF_PATTERN.regex.search("123456789012")
    assert m is None


def test_fr_nif_label():
    assert FR_NIF_PATTERN.label == "FR_NIF"


def test_fr_nif_confidence():
    assert FR_NIF_PATTERN.confidence == 0.99
```

- [ ] **Step 2: Run to confirm failure**

```
uv run pytest tests/unit/detector/patterns/test_national_id.py -v
```

Expected: `ImportError: cannot import name 'FR_PERMIS_CONDUIRE_PATTERN'`

- [ ] **Step 3: Implement the two patterns in national_id.py**

Append to `src/piighost/detector/patterns/national_id.py` (after the existing `FR_PASSPORT_PATTERN` block):

```python
# French driving licence (EU-harmonised format, issued since ~2013).
# Format: 2 digits + 2 uppercase letters + 6 digits = 10 chars, e.g. 07AB123456.
# Deliberately distinct from FR_PASSPORT biometric (\d{2}[A-Z]{2}\d{5}, 9 chars).
# No public checksum algorithm exists; pattern length is the sole discriminator.
_FR_PERMIS_RE = re.compile(r"\b\d{2}[A-Z]{2}\d{6}\b")

FR_PERMIS_CONDUIRE_PATTERN = Pattern(
    label="FR_PERMIS_CONDUIRE",
    regex=_FR_PERMIS_RE,
)

# French individual tax identifier (numéro fiscal / SPI), always 13 digits.
# Must precede CREDIT_CARD in DEFAULT_PATTERNS: old 13-digit Visa cards also
# pass Luhn, but are vanishingly rare in French legal documents.
_FR_NIF_RE = re.compile(r"\b\d{13}\b")

FR_NIF_PATTERN = Pattern(
    label="FR_NIF",
    regex=_FR_NIF_RE,
)
```

- [ ] **Step 4: Run tests to confirm they pass**

```
uv run pytest tests/unit/detector/patterns/test_national_id.py -v
```

Expected: all tests pass, 0 failures.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/detector/patterns/test_national_id.py \
        src/piighost/detector/patterns/national_id.py
git commit -m "feat(patterns): add FR_PERMIS_CONDUIRE and FR_NIF patterns

FR_PERMIS_CONDUIRE matches the EU-harmonised 10-char DL format (2d+2A+6d).
FR_NIF matches the 13-digit French individual tax identifier.
Both are new GDPR personal data categories not previously covered."
```

---

## Task 2: URL pattern

**Files:**
- Create: `tests/unit/detector/patterns/test_url.py`
- Create: `src/piighost/detector/patterns/url.py`

### Background

URLs are online identifiers under GDPR Article 4(1) when they uniquely identify a person (e.g. a profile URL). The pattern requires an explicit scheme (`http://` or `https://`) to avoid false-positives on bare domain names.  
No validator needed — the scheme prefix is specific enough.

---

- [ ] **Step 1: Write the failing test**

Create `tests/unit/detector/patterns/test_url.py`:

```python
from piighost.detector.patterns.url import URL_PATTERN


def test_matches_http_url():
    m = URL_PATTERN.regex.search("visit http://example.com today")
    assert m is not None
    assert m.group(0) == "http://example.com"


def test_matches_https_url_with_path():
    m = URL_PATTERN.regex.search("see https://piighost.eu/docs/api for details")
    assert m is not None
    assert m.group(0) == "https://piighost.eu/docs/api"


def test_no_match_bare_domain():
    m = URL_PATTERN.regex.search("visit example.com")
    assert m is None


def test_no_match_email():
    # email doesn't start with http(s)://
    m = URL_PATTERN.regex.search("contact alice@example.com")
    assert m is None


def test_url_label():
    assert URL_PATTERN.label == "URL"


def test_url_confidence():
    assert URL_PATTERN.confidence == 0.99
```

- [ ] **Step 2: Run to confirm failure**

```
uv run pytest tests/unit/detector/patterns/test_url.py -v
```

Expected: `ModuleNotFoundError: No module named 'piighost.detector.patterns.url'`

- [ ] **Step 3: Implement url.py**

Create `src/piighost/detector/patterns/url.py`:

```python
from __future__ import annotations

import re

from piighost.detector.patterns._base import Pattern

# Matches http:// and https:// URLs. The negative character class stops at
# whitespace and common HTML delimiters to avoid consuming surrounding text.
_URL_RE = re.compile(r"https?://[^\s<>\"']+")

URL_PATTERN = Pattern(
    label="URL",
    regex=_URL_RE,
)
```

- [ ] **Step 4: Run tests to confirm they pass**

```
uv run pytest tests/unit/detector/patterns/test_url.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/detector/patterns/test_url.py \
        src/piighost/detector/patterns/url.py
git commit -m "feat(patterns): add URL pattern for GDPR Art. 4 online identifiers

Profile URLs and personal pages are online identifiers under GDPR Art. 4(1).
Requires explicit http(s):// scheme to avoid false-positives on bare domains."
```

---

## Task 3: Wire new patterns into DEFAULT_PATTERNS

**Files:**
- Modify: `src/piighost/detector/patterns/__init__.py`

### Background

Two ordering rules govern this file:
1. **FR_SIRET before CREDIT_CARD** (already in place) — 14-digit Luhn overlap.
2. **FR_NIF before CREDIT_CARD** (new) — 13-digit potential Luhn overlap (old Visa format).

`FR_PERMIS_CONDUIRE` and `URL_PATTERN` have no ordering constraints relative to existing patterns.

---

- [ ] **Step 1: Write a failing integration test**

Append to `tests/unit/detector/test_regex_detector.py`:

```python
def test_detector_finds_french_driving_licence():
    det = RegexDetector()
    hits = asyncio.run(det.detect("permis 07AB123456 valide"))
    assert any(d.label == "FR_PERMIS_CONDUIRE" for d in hits)


def test_detector_finds_french_nif():
    det = RegexDetector()
    hits = asyncio.run(det.detect("NIF fiscal 1234567890123"))
    assert any(d.label == "FR_NIF" for d in hits)


def test_detector_finds_url():
    det = RegexDetector()
    hits = asyncio.run(det.detect("profil https://linkedin.com/in/jean-dupont"))
    assert any(d.label == "URL" for d in hits)


def test_nif_wins_over_credit_card_for_13_digits():
    # A 13-digit number that also passes Luhn should be labelled FR_NIF,
    # not CREDIT_CARD, because FR_NIF is ordered first.
    det = RegexDetector()
    hits = asyncio.run(det.detect("numéro fiscal 4532015112830"))  # 13-digit Luhn
    labels = [d.label for d in hits]
    assert "FR_NIF" in labels
    assert "CREDIT_CARD" not in labels
```

- [ ] **Step 2: Run to confirm failure**

```
uv run pytest tests/unit/detector/test_regex_detector.py -v
```

Expected: 4 new test failures (imports succeed, patterns not yet in DEFAULT_PATTERNS).

- [ ] **Step 3: Update __init__.py**

Replace the full contents of `src/piighost/detector/patterns/__init__.py` with:

```python
from __future__ import annotations

from piighost.detector.patterns._base import Pattern
from piighost.detector.patterns.credit_card import CREDIT_CARD_PATTERN
from piighost.detector.patterns.date import DATE_PATTERN
from piighost.detector.patterns.email import EMAIL_PATTERN
from piighost.detector.patterns.iban import IBAN_PATTERN
from piighost.detector.patterns.ip import IPV4_PATTERN, IPV6_PATTERN
from piighost.detector.patterns.national_id import (
    DE_PERSONALAUSWEIS_PATTERN,
    FR_NIR_PATTERN,
    FR_NIF_PATTERN,
    FR_PASSPORT_PATTERN,
    FR_PERMIS_CONDUIRE_PATTERN,
    FR_SIRET_PATTERN,
)
from piighost.detector.patterns.phone import PHONE_PATTERN
from piighost.detector.patterns.url import URL_PATTERN
from piighost.detector.patterns.vat import VAT_PATTERN

DEFAULT_PATTERNS: list[Pattern] = [
    EMAIL_PATTERN,
    PHONE_PATTERN,
    IPV4_PATTERN,
    IPV6_PATTERN,
    URL_PATTERN,
    # FR_SIRET and FR_NIF must precede CREDIT_CARD: both are digit-only sequences
    # (14d and 13d) that can coincide with Luhn-valid payment card numbers.
    # The overlap resolver keeps the first match per span. In French legal
    # documents these lengths almost never represent payment cards.
    FR_SIRET_PATTERN,
    FR_NIF_PATTERN,
    CREDIT_CARD_PATTERN,
    IBAN_PATTERN,
    VAT_PATTERN,
    DATE_PATTERN,
    FR_NIR_PATTERN,
    FR_PERMIS_CONDUIRE_PATTERN,
    FR_PASSPORT_PATTERN,
    DE_PERSONALAUSWEIS_PATTERN,
]
```

- [ ] **Step 4: Run all pattern and detector tests**

```
uv run pytest tests/unit/detector/ -v
```

Expected: all tests pass, 0 failures.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/detector/patterns/__init__.py \
        tests/unit/detector/test_regex_detector.py
git commit -m "feat(patterns): wire FR_PERMIS_CONDUIRE, FR_NIF, URL into DEFAULT_PATTERNS

FR_NIF ordered before CREDIT_CARD (13-digit Luhn overlap).
URL added after IPv6 (no ordering constraint).
FR_PERMIS_CONDUIRE added after FR_NIR (no ordering constraint)."
```

---

## Task 4: Add appartenance_syndicale NER label

**Files:**
- Modify: `scripts/test_french_model.py`
- Modify: `.piighost/config.toml`

### Background

Trade union membership is a GDPR Article 9 special category. It is the only Art. 9 category absent from the French model's label vocabulary. GLiNER2 is **zero-shot**: adding the label `"appartenance_syndicale"` to the query list causes the model to look for semantically matching spans without retraining. The external label for this category is `TRADE_UNION`.

---

- [ ] **Step 1: Add to LABEL_MAP in test_french_model.py**

In `scripts/test_french_model.py`, find the `LABEL_MAP` dict and add one entry at the end, before the closing `}`:

```python
LABEL_MAP: dict[str, str] = {
    # ... existing entries unchanged ...
    "condamnation_penale":      "CRIMINAL",
    "base_legale_traitement":   "LEGAL_BASIS",
    "appartenance_syndicale":   "TRADE_UNION",   # ← add this line
}
```

- [ ] **Step 2: Add a syndicat sample to SAMPLES**

In `scripts/test_french_model.py`, add this tuple at the end of the `SAMPLES` list (before the closing `]`):

```python
SAMPLES = [
    # ... existing samples unchanged ...
    (
        "syndicat",
        "M. François Dupont, délégué syndical CGT au sein de Renault SA depuis "
        "janvier 2015, a saisi le tribunal prud'homal concernant son appartenance "
        "syndicale et les discriminations subies de ce fait par son employeur.",
    ),
]
```

- [ ] **Step 3: Update .piighost/config.toml**

In `.piighost/config.toml`, add `"appartenance_syndicale"` to the `labels` array under `[detector]`. The final list should be (alphabetical order is not required, append to end):

```toml
[detector]
backend = "gliner2"
gliner2_model = "jamon8888/french-pii-legal-ner-quantized"
threshold = 0.4
labels = [
    "adresse", "avocat", "base_legale_traitement", "condamnation_penale",
    "date", "date_naissance", "donnee_biometrique", "donnee_genetique",
    "donnee_sante", "email", "juge", "lieu", "lieu_naissance", "nationalite",
    "nom_personne", "notaire", "numero_affaire", "numero_carte_identite",
    "numero_compte_bancaire", "numero_passeport", "numero_securite_sociale",
    "numero_siret", "numero_telephone", "opinion_politique", "organisation",
    "orientation_sexuelle", "origine_ethnique", "plaque_immatriculation",
    "prenom", "profession", "religion", "salaire", "tribunal",
    "appartenance_syndicale",
]
```

- [ ] **Step 4: Verify the smoke test runs without errors**

```
uv run python scripts/test_french_model.py
```

Expected: model loads, all 4 samples processed (contrat, jugement, medical, syndicat), output printed for thresholds 0.40 and 0.30. No exceptions. The syndicat sample should show `appartenance_syndicale` detections at threshold ≤ 0.30 (zero-shot recall; score may be low on a domain-specialised model).

- [ ] **Step 5: Commit**

```bash
git add scripts/test_french_model.py .piighost/config.toml
git commit -m "feat(ner): add appartenance_syndicale label for GDPR Art. 9 trade union membership

Closes the only remaining GDPR Article 9 gap. GLiNER2 is zero-shot so no
retraining is required; the model will attempt detection based on label semantics.
Production config.toml updated to include the new label."
```

---

## Final verification

After all four tasks are committed:

- [ ] **Run the full test suite** (excluding the pre-existing daemon routing failure):

```
uv run pytest tests/ --ignore=tests/cli/test_daemon_routing.py -q
```

Expected: all tests pass, 0 failures, ≥ 122 tests collected.

- [ ] **Run the end-to-end smoke test**:

```
uv run python scripts/test_french_model.py
```

Expected: no exceptions; syndicat sample outputs `appartenance_syndicale` detections at threshold 0.30.
