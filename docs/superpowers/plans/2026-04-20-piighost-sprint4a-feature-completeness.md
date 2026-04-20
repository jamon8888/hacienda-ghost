# piighost Sprint 4a — Feature Completeness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three known feature gaps — regex-only detector, MCP `reveal` propagation, and Mistral embedder API key validation — so every documented config option works.

**Architecture:** A new `piighost.detector.regex` package with one `Pattern` module per entity type, exporting a `DEFAULT_PATTERNS` list. `RegexDetector` iterates patterns, validates matches (Luhn, mod-97, NIR key, etc.), and resolves overlaps deterministically. Wired into `_build_default_detector` via `backend="regex_only"`. Separately: MCP `vault_list` gains a `reveal` parameter and propagates it; `MistralEmbedder` raises at construction if `MISTRAL_API_KEY` is missing.

**Tech Stack:** Python 3.10+, `re` (stdlib), `datetime` (for DOB validation), existing `Detection`/`Span` models, FastMCP 2.14, pytest.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `src/piighost/detector/__init__.py` | Empty package marker (if missing) |
| Create | `src/piighost/detector/regex.py` | `RegexDetector` + `_resolve_overlaps` |
| Create | `src/piighost/detector/patterns/__init__.py` | Re-export `DEFAULT_PATTERNS` list |
| Create | `src/piighost/detector/patterns/_base.py` | `Pattern` dataclass |
| Create | `src/piighost/detector/patterns/email.py` | `EMAIL_PATTERN` |
| Create | `src/piighost/detector/patterns/phone.py` | `PHONE_PATTERN` |
| Create | `src/piighost/detector/patterns/ip.py` | `IPV4_PATTERN`, `IPV6_PATTERN` |
| Create | `src/piighost/detector/patterns/credit_card.py` | `CREDIT_CARD_PATTERN` + Luhn validator |
| Create | `src/piighost/detector/patterns/iban.py` | `IBAN_PATTERN` + mod-97 validator |
| Create | `src/piighost/detector/patterns/vat.py` | `VAT_PATTERN` + country-format validator |
| Create | `src/piighost/detector/patterns/date.py` | `DATE_PATTERN` + calendar validator |
| Create | `src/piighost/detector/patterns/national_id.py` | `FR_NIR_PATTERN` + `DE_PERSONALAUSWEIS_PATTERN` |
| Modify | `src/piighost/service/core.py` | Route `backend="regex_only"` to `RegexDetector` |
| Modify | `src/piighost/mcp/server.py` | Add `reveal` to `vault_list`, propagate it |
| Modify | `src/piighost/indexer/embedder.py` | `MistralEmbedder` raises if `MISTRAL_API_KEY` empty |
| Create | `tests/unit/detector/patterns/test_email.py` | Email match + negative |
| Create | `tests/unit/detector/patterns/test_phone.py` | Phone match + negative |
| Create | `tests/unit/detector/patterns/test_ip.py` | IPv4/IPv6 match + octet-range validator |
| Create | `tests/unit/detector/patterns/test_credit_card.py` | Luhn pass/fail |
| Create | `tests/unit/detector/patterns/test_iban.py` | mod-97 pass/fail |
| Create | `tests/unit/detector/patterns/test_vat.py` | Per-country format |
| Create | `tests/unit/detector/patterns/test_date.py` | Valid + invalid calendar dates |
| Create | `tests/unit/detector/patterns/test_national_id.py` | FR NIR key + DE checksum |
| Create | `tests/unit/detector/test_regex_detector.py` | Multi-pattern detect + overlap resolution |
| Create | `tests/unit/test_detector_wiring.py` | `_build_default_detector` routes `regex_only` |
| Create | `tests/unit/test_mcp_reveal.py` | MCP `vault_list` reveal propagation |
| Create | `tests/unit/indexer/test_mistral_embedder.py` | API key validation |

---

### Task 1: Foundation — `Pattern` dataclass + `RegexDetector` shell with email pattern

**Files:**
- Create: `src/piighost/detector/__init__.py` (empty if missing)
- Create: `src/piighost/detector/patterns/__init__.py`
- Create: `src/piighost/detector/patterns/_base.py`
- Create: `src/piighost/detector/patterns/email.py`
- Create: `src/piighost/detector/regex.py`
- Create: `tests/unit/detector/__init__.py` (empty, if fixtures need it — check existing `tests/unit/indexer/` for pattern)
- Create: `tests/unit/detector/patterns/__init__.py` (empty if needed)
- Create: `tests/unit/detector/patterns/test_email.py`
- Create: `tests/unit/detector/test_regex_detector.py`

- [ ] **Step 1: Check whether `src/piighost/detector/` already exists**

```bash
cd C:/Users/NMarchitecte/Documents/piighost
ls src/piighost/detector/ 2>&1
```

If it exists (likely, since `Gliner2Detector` lives there), skip creating `__init__.py`. If not, create empty `__init__.py`. Also check `tests/unit/` for `__init__.py` convention — follow whatever the existing `tests/unit/indexer/` does.

- [ ] **Step 2: Write the failing test for email pattern**

Create `tests/unit/detector/patterns/test_email.py`:

```python
from piighost.detector.patterns.email import EMAIL_PATTERN


def test_matches_simple_email():
    m = EMAIL_PATTERN.regex.search("contact alice@example.com today")
    assert m is not None
    assert m.group(0) == "alice@example.com"


def test_matches_email_with_subdomain():
    m = EMAIL_PATTERN.regex.search("Send to bob.smith@mail.company.co.uk please")
    assert m is not None
    assert m.group(0) == "bob.smith@mail.company.co.uk"


def test_matches_plus_addressing():
    m = EMAIL_PATTERN.regex.search("alice+filter@example.com")
    assert m is not None
    assert m.group(0) == "alice+filter@example.com"


def test_does_not_match_plain_text():
    assert EMAIL_PATTERN.regex.search("no email here") is None


def test_label_is_email_address():
    assert EMAIL_PATTERN.label == "EMAIL_ADDRESS"
```

- [ ] **Step 3: Run test to verify it fails**

```bash
python -m pytest tests/unit/detector/patterns/test_email.py -v -p no:randomly
```

Expected: `ModuleNotFoundError: No module named 'piighost.detector.patterns'`.

- [ ] **Step 4: Implement `Pattern` dataclass**

Create `src/piighost/detector/patterns/_base.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Pattern:
    label: str
    regex: re.Pattern[str]
    validator: Callable[[str], bool] | None = None
    confidence: float = 0.99
```

- [ ] **Step 5: Implement email pattern**

Create `src/piighost/detector/patterns/email.py`:

```python
from __future__ import annotations

import re

from piighost.detector.patterns._base import Pattern

_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

EMAIL_PATTERN = Pattern(label="EMAIL_ADDRESS", regex=_EMAIL_RE)
```

- [ ] **Step 6: Create `patterns/__init__.py` with placeholder `DEFAULT_PATTERNS`**

```python
from __future__ import annotations

from piighost.detector.patterns._base import Pattern
from piighost.detector.patterns.email import EMAIL_PATTERN

DEFAULT_PATTERNS: list[Pattern] = [EMAIL_PATTERN]
```

- [ ] **Step 7: Run email tests to verify they pass**

```bash
python -m pytest tests/unit/detector/patterns/test_email.py -v -p no:randomly
```

Expected: 5 PASSED.

- [ ] **Step 8: Write the failing test for `RegexDetector`**

Create `tests/unit/detector/test_regex_detector.py`:

```python
import asyncio
from piighost.detector.regex import RegexDetector


def test_detector_finds_email():
    det = RegexDetector()
    detections = asyncio.run(det.detect("Email alice@example.com for info"))
    assert len(detections) == 1
    assert detections[0].label == "EMAIL_ADDRESS"
    assert detections[0].text == "alice@example.com"


def test_detector_finds_multiple_emails():
    det = RegexDetector()
    detections = asyncio.run(det.detect("a@b.com and c@d.org"))
    assert len(detections) == 2
    assert {d.text for d in detections} == {"a@b.com", "c@d.org"}


def test_detector_empty_text():
    det = RegexDetector()
    detections = asyncio.run(det.detect(""))
    assert detections == []


def test_detector_no_matches():
    det = RegexDetector()
    detections = asyncio.run(det.detect("just plain text"))
    assert detections == []


def test_detection_has_correct_positions():
    det = RegexDetector()
    text = "Email alice@example.com now"
    detections = asyncio.run(det.detect(text))
    assert detections[0].position.start_pos == 6
    assert detections[0].position.end_pos == 23
```

- [ ] **Step 9: Run test to verify it fails**

```bash
python -m pytest tests/unit/detector/test_regex_detector.py -v -p no:randomly
```

Expected: `ModuleNotFoundError: No module named 'piighost.detector.regex'`.

- [ ] **Step 10: Implement `RegexDetector`**

Create `src/piighost/detector/regex.py`:

```python
from __future__ import annotations

from piighost.detector.patterns import DEFAULT_PATTERNS
from piighost.detector.patterns._base import Pattern
from piighost.models import Detection, Span


class RegexDetector:
    def __init__(self, patterns: list[Pattern] | None = None) -> None:
        self._patterns = patterns if patterns is not None else DEFAULT_PATTERNS

    async def detect(self, text: str) -> list[Detection]:
        out: list[Detection] = []
        for pattern in self._patterns:
            for m in pattern.regex.finditer(text):
                matched = m.group(0)
                if pattern.validator is not None:
                    try:
                        if not pattern.validator(matched):
                            continue
                    except Exception:
                        continue
                out.append(
                    Detection(
                        text=matched,
                        label=pattern.label,
                        position=Span(start_pos=m.start(), end_pos=m.end()),
                        confidence=pattern.confidence,
                    )
                )
        return _resolve_overlaps(out)


def _resolve_overlaps(detections: list[Detection]) -> list[Detection]:
    detections.sort(
        key=lambda d: (
            d.position.start_pos,
            -(d.position.end_pos - d.position.start_pos),
        )
    )
    accepted: list[Detection] = []
    for d in detections:
        if accepted and d.position.start_pos < accepted[-1].position.end_pos:
            continue
        accepted.append(d)
    return accepted
```

- [ ] **Step 11: Run all new tests to verify they pass**

```bash
python -m pytest tests/unit/detector/ -v -p no:randomly
```

Expected: 10 PASSED (5 email + 5 detector).

- [ ] **Step 12: Commit**

```bash
cd C:/Users/NMarchitecte/Documents/piighost
git add src/piighost/detector/patterns/_base.py \
        src/piighost/detector/patterns/__init__.py \
        src/piighost/detector/patterns/email.py \
        src/piighost/detector/regex.py \
        tests/unit/detector/test_regex_detector.py \
        tests/unit/detector/patterns/test_email.py
git commit -m "feat(detector): RegexDetector foundation + EMAIL_ADDRESS pattern"
```

---

### Task 2: Phone + IP address patterns

**Files:**
- Create: `src/piighost/detector/patterns/phone.py`
- Create: `src/piighost/detector/patterns/ip.py`
- Modify: `src/piighost/detector/patterns/__init__.py` (add new patterns to `DEFAULT_PATTERNS`)
- Create: `tests/unit/detector/patterns/test_phone.py`
- Create: `tests/unit/detector/patterns/test_ip.py`

- [ ] **Step 1: Write failing phone test**

Create `tests/unit/detector/patterns/test_phone.py`:

```python
from piighost.detector.patterns.phone import PHONE_PATTERN


def test_matches_french_mobile():
    m = PHONE_PATTERN.regex.search("call +33 6 12 34 56 78 tomorrow")
    assert m is not None
    assert "+33 6 12 34 56 78" in m.group(0)


def test_matches_german_number():
    m = PHONE_PATTERN.regex.search("Reach us at +49 30 12345678")
    assert m is not None
    assert "+49 30 12345678" in m.group(0)


def test_matches_uk_number():
    m = PHONE_PATTERN.regex.search("phone +44 20 7946 0958 now")
    assert m is not None


def test_rejects_plain_digits():
    assert PHONE_PATTERN.regex.search("1234567") is None


def test_validator_rejects_too_short():
    assert PHONE_PATTERN.validator is not None
    assert PHONE_PATTERN.validator("+33 1") is False


def test_validator_accepts_normal_length():
    assert PHONE_PATTERN.validator("+33 6 12 34 56 78") is True


def test_label_is_phone_number():
    assert PHONE_PATTERN.label == "PHONE_NUMBER"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/detector/patterns/test_phone.py -v -p no:randomly
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement phone pattern**

Create `src/piighost/detector/patterns/phone.py`:

```python
from __future__ import annotations

import re

from piighost.detector.patterns._base import Pattern

_PHONE_RE = re.compile(
    r"\+\d{1,3}(?:[ .\-]?\d{1,4}){2,6}"
)


def _phone_validator(text: str) -> bool:
    digits = [c for c in text if c.isdigit()]
    return 7 <= len(digits) <= 15


PHONE_PATTERN = Pattern(
    label="PHONE_NUMBER",
    regex=_PHONE_RE,
    validator=_phone_validator,
)
```

- [ ] **Step 4: Run phone tests**

```bash
python -m pytest tests/unit/detector/patterns/test_phone.py -v -p no:randomly
```

Expected: 7 PASSED.

- [ ] **Step 5: Write failing IP test**

Create `tests/unit/detector/patterns/test_ip.py`:

```python
from piighost.detector.patterns.ip import IPV4_PATTERN, IPV6_PATTERN


def test_ipv4_matches_address():
    m = IPV4_PATTERN.regex.search("server 192.168.1.1 up")
    assert m is not None
    assert m.group(0) == "192.168.1.1"


def test_ipv4_validator_rejects_out_of_range():
    assert IPV4_PATTERN.validator("256.1.2.3") is False


def test_ipv4_validator_accepts_zero():
    assert IPV4_PATTERN.validator("0.0.0.0") is True


def test_ipv4_validator_accepts_max():
    assert IPV4_PATTERN.validator("255.255.255.255") is True


def test_ipv6_matches_full_address():
    m = IPV6_PATTERN.regex.search("addr 2001:0db8:85a3:0000:0000:8a2e:0370:7334 is")
    assert m is not None


def test_ipv6_matches_compressed():
    m = IPV6_PATTERN.regex.search("loopback ::1 set")
    assert m is not None


def test_ipv4_label():
    assert IPV4_PATTERN.label == "IP_ADDRESS"


def test_ipv6_label():
    assert IPV6_PATTERN.label == "IP_ADDRESS"
```

- [ ] **Step 6: Run test to verify it fails**

```bash
python -m pytest tests/unit/detector/patterns/test_ip.py -v -p no:randomly
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 7: Implement IP patterns**

Create `src/piighost/detector/patterns/ip.py`:

```python
from __future__ import annotations

import re

from piighost.detector.patterns._base import Pattern

_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6_RE = re.compile(
    r"(?:"
    r"(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}"
    r"|::(?:[0-9A-Fa-f]{1,4}:){0,6}[0-9A-Fa-f]{1,4}"
    r"|(?:[0-9A-Fa-f]{1,4}:){1,7}:"
    r")"
)


def _ipv4_validator(text: str) -> bool:
    parts = text.split(".")
    if len(parts) != 4:
        return False
    return all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


IPV4_PATTERN = Pattern(
    label="IP_ADDRESS",
    regex=_IPV4_RE,
    validator=_ipv4_validator,
)

IPV6_PATTERN = Pattern(
    label="IP_ADDRESS",
    regex=_IPV6_RE,
)
```

- [ ] **Step 8: Run IP tests**

```bash
python -m pytest tests/unit/detector/patterns/test_ip.py -v -p no:randomly
```

Expected: 8 PASSED.

- [ ] **Step 9: Register new patterns in `__init__.py`**

Replace `src/piighost/detector/patterns/__init__.py` with:

```python
from __future__ import annotations

from piighost.detector.patterns._base import Pattern
from piighost.detector.patterns.email import EMAIL_PATTERN
from piighost.detector.patterns.ip import IPV4_PATTERN, IPV6_PATTERN
from piighost.detector.patterns.phone import PHONE_PATTERN

DEFAULT_PATTERNS: list[Pattern] = [
    EMAIL_PATTERN,
    PHONE_PATTERN,
    IPV4_PATTERN,
    IPV6_PATTERN,
]
```

- [ ] **Step 10: Run full detector suite to verify no regression**

```bash
python -m pytest tests/unit/detector/ -v -p no:randomly
```

Expected: all passing.

- [ ] **Step 11: Commit**

```bash
git add src/piighost/detector/patterns/phone.py \
        src/piighost/detector/patterns/ip.py \
        src/piighost/detector/patterns/__init__.py \
        tests/unit/detector/patterns/test_phone.py \
        tests/unit/detector/patterns/test_ip.py
git commit -m "feat(detector): PHONE_NUMBER and IP_ADDRESS patterns"
```

---

### Task 3: Credit card + IBAN patterns with validators

**Files:**
- Create: `src/piighost/detector/patterns/credit_card.py`
- Create: `src/piighost/detector/patterns/iban.py`
- Modify: `src/piighost/detector/patterns/__init__.py` (add to `DEFAULT_PATTERNS`)
- Create: `tests/unit/detector/patterns/test_credit_card.py`
- Create: `tests/unit/detector/patterns/test_iban.py`

- [ ] **Step 1: Write failing credit card test**

Create `tests/unit/detector/patterns/test_credit_card.py`:

```python
from piighost.detector.patterns.credit_card import CREDIT_CARD_PATTERN


def test_matches_visa():
    # Valid Luhn: 4532 0151 1283 0366
    m = CREDIT_CARD_PATTERN.regex.search("pay 4532 0151 1283 0366 now")
    assert m is not None


def test_matches_no_separators():
    m = CREDIT_CARD_PATTERN.regex.search("card 4532015112830366")
    assert m is not None


def test_validator_accepts_valid_luhn():
    assert CREDIT_CARD_PATTERN.validator("4532 0151 1283 0366") is True


def test_validator_rejects_invalid_luhn():
    assert CREDIT_CARD_PATTERN.validator("4532 0151 1283 0367") is False


def test_validator_rejects_too_short():
    assert CREDIT_CARD_PATTERN.validator("1234567") is False


def test_validator_accepts_amex_15_digits():
    # 378282246310005 is a test AMEX number with valid Luhn
    assert CREDIT_CARD_PATTERN.validator("378282246310005") is True


def test_label_is_credit_card():
    assert CREDIT_CARD_PATTERN.label == "CREDIT_CARD"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/detector/patterns/test_credit_card.py -v -p no:randomly
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement credit card pattern**

Create `src/piighost/detector/patterns/credit_card.py`:

```python
from __future__ import annotations

import re

from piighost.detector.patterns._base import Pattern

_CC_RE = re.compile(r"\b(?:\d[ \-]?){12,18}\d\b")


def _luhn_valid(text: str) -> bool:
    digits = [int(c) for c in text if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


CREDIT_CARD_PATTERN = Pattern(
    label="CREDIT_CARD",
    regex=_CC_RE,
    validator=_luhn_valid,
)
```

- [ ] **Step 4: Run credit card tests**

```bash
python -m pytest tests/unit/detector/patterns/test_credit_card.py -v -p no:randomly
```

Expected: 7 PASSED.

- [ ] **Step 5: Write failing IBAN test**

Create `tests/unit/detector/patterns/test_iban.py`:

```python
from piighost.detector.patterns.iban import IBAN_PATTERN


def test_matches_french_iban():
    # FR76 3000 6000 0112 3456 7890 189 — valid mod-97
    m = IBAN_PATTERN.regex.search("IBAN FR76 3000 6000 0112 3456 7890 189 please")
    assert m is not None


def test_matches_german_iban():
    # DE89 3704 0044 0532 0130 00 — valid mod-97
    m = IBAN_PATTERN.regex.search("DE89370400440532013000 on file")
    assert m is not None


def test_validator_accepts_valid_iban():
    assert IBAN_PATTERN.validator("DE89370400440532013000") is True


def test_validator_rejects_invalid_checksum():
    # Change last digits to break mod-97
    assert IBAN_PATTERN.validator("DE89370400440532013099") is False


def test_validator_rejects_too_short():
    assert IBAN_PATTERN.validator("DE12") is False


def test_label_is_iban_code():
    assert IBAN_PATTERN.label == "IBAN_CODE"
```

- [ ] **Step 6: Run test to verify it fails**

```bash
python -m pytest tests/unit/detector/patterns/test_iban.py -v -p no:randomly
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 7: Implement IBAN pattern**

Create `src/piighost/detector/patterns/iban.py`:

```python
from __future__ import annotations

import re

from piighost.detector.patterns._base import Pattern

_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b")


def _iban_mod97(text: str) -> bool:
    normalized = "".join(c for c in text if c.isalnum()).upper()
    if not 15 <= len(normalized) <= 34:
        return False
    if not normalized[:2].isalpha() or not normalized[2:4].isdigit():
        return False
    rearranged = normalized[4:] + normalized[:4]
    converted = "".join(
        str(ord(c) - 55) if c.isalpha() else c for c in rearranged
    )
    try:
        return int(converted) % 97 == 1
    except ValueError:
        return False


IBAN_PATTERN = Pattern(
    label="IBAN_CODE",
    regex=_IBAN_RE,
    validator=_iban_mod97,
)
```

- [ ] **Step 8: Run IBAN tests**

```bash
python -m pytest tests/unit/detector/patterns/test_iban.py -v -p no:randomly
```

Expected: 6 PASSED.

- [ ] **Step 9: Register new patterns in `__init__.py`**

Replace `src/piighost/detector/patterns/__init__.py` with:

```python
from __future__ import annotations

from piighost.detector.patterns._base import Pattern
from piighost.detector.patterns.credit_card import CREDIT_CARD_PATTERN
from piighost.detector.patterns.email import EMAIL_PATTERN
from piighost.detector.patterns.iban import IBAN_PATTERN
from piighost.detector.patterns.ip import IPV4_PATTERN, IPV6_PATTERN
from piighost.detector.patterns.phone import PHONE_PATTERN

DEFAULT_PATTERNS: list[Pattern] = [
    EMAIL_PATTERN,
    PHONE_PATTERN,
    IPV4_PATTERN,
    IPV6_PATTERN,
    CREDIT_CARD_PATTERN,
    IBAN_PATTERN,
]
```

- [ ] **Step 10: Run full detector suite**

```bash
python -m pytest tests/unit/detector/ -v -p no:randomly
```

Expected: all passing.

- [ ] **Step 11: Commit**

```bash
git add src/piighost/detector/patterns/credit_card.py \
        src/piighost/detector/patterns/iban.py \
        src/piighost/detector/patterns/__init__.py \
        tests/unit/detector/patterns/test_credit_card.py \
        tests/unit/detector/patterns/test_iban.py
git commit -m "feat(detector): CREDIT_CARD (Luhn) and IBAN_CODE (mod-97) patterns"
```

---

### Task 4: VAT + Date patterns

**Files:**
- Create: `src/piighost/detector/patterns/vat.py`
- Create: `src/piighost/detector/patterns/date.py`
- Modify: `src/piighost/detector/patterns/__init__.py`
- Create: `tests/unit/detector/patterns/test_vat.py`
- Create: `tests/unit/detector/patterns/test_date.py`

- [ ] **Step 1: Write failing VAT test**

Create `tests/unit/detector/patterns/test_vat.py`:

```python
from piighost.detector.patterns.vat import VAT_PATTERN


def test_matches_french_vat():
    m = VAT_PATTERN.regex.search("VAT FR12345678901 applies")
    assert m is not None
    assert m.group(0) == "FR12345678901"


def test_matches_german_vat():
    m = VAT_PATTERN.regex.search("vendor DE123456789 registered")
    assert m is not None


def test_matches_uk_vat():
    m = VAT_PATTERN.regex.search("invoice GB123456789")
    assert m is not None


def test_does_not_match_invalid_prefix():
    assert VAT_PATTERN.regex.search("XY123456789") is None


def test_label_is_eu_vat():
    assert VAT_PATTERN.label == "EU_VAT"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/detector/patterns/test_vat.py -v -p no:randomly
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement VAT pattern**

Create `src/piighost/detector/patterns/vat.py`:

```python
from __future__ import annotations

import re

from piighost.detector.patterns._base import Pattern

_EU_COUNTRY_CODES = (
    "AT|BE|BG|CY|CZ|DE|DK|EE|EL|ES|FI|FR|GB|HR|HU|IE|IT|LT|LU|LV|"
    "MT|NL|PL|PT|RO|SE|SI|SK"
)

_VAT_RE = re.compile(
    rf"\b(?:{_EU_COUNTRY_CODES})[A-Z0-9]{{8,12}}\b"
)

VAT_PATTERN = Pattern(
    label="EU_VAT",
    regex=_VAT_RE,
)
```

- [ ] **Step 4: Run VAT tests**

```bash
python -m pytest tests/unit/detector/patterns/test_vat.py -v -p no:randomly
```

Expected: 5 PASSED.

- [ ] **Step 5: Write failing date test**

Create `tests/unit/detector/patterns/test_date.py`:

```python
from piighost.detector.patterns.date import DATE_PATTERN


def test_matches_slash_date():
    m = DATE_PATTERN.regex.search("born 15/03/1990 today")
    assert m is not None
    assert m.group(0) == "15/03/1990"


def test_matches_iso_date():
    m = DATE_PATTERN.regex.search("DOB 1990-03-15 confirmed")
    assert m is not None


def test_matches_dot_date():
    m = DATE_PATTERN.regex.search("Geburtsdatum 15.03.1990 ok")
    assert m is not None


def test_validator_rejects_invalid_month():
    assert DATE_PATTERN.validator("15/13/1990") is False


def test_validator_rejects_invalid_day():
    assert DATE_PATTERN.validator("32/01/1990") is False


def test_validator_accepts_leap_day():
    assert DATE_PATTERN.validator("29/02/2000") is True


def test_validator_rejects_non_leap_feb_29():
    assert DATE_PATTERN.validator("29/02/1999") is False


def test_label_is_date_time():
    assert DATE_PATTERN.label == "DATE_TIME"
```

- [ ] **Step 6: Run test to verify it fails**

```bash
python -m pytest tests/unit/detector/patterns/test_date.py -v -p no:randomly
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 7: Implement date pattern**

Create `src/piighost/detector/patterns/date.py`:

```python
from __future__ import annotations

import re
from datetime import date

from piighost.detector.patterns._base import Pattern

_DATE_RE = re.compile(
    r"\b(?:"
    r"\d{1,2}[./\-]\d{1,2}[./\-]\d{4}"
    r"|\d{4}-\d{2}-\d{2}"
    r")\b"
)


def _date_validator(text: str) -> bool:
    parts = re.split(r"[./\-]", text)
    if len(parts) != 3:
        return False
    try:
        if len(parts[0]) == 4:  # ISO: YYYY-MM-DD
            year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        else:  # DD/MM/YYYY
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
        date(year, month, day)
        return True
    except (ValueError, IndexError):
        return False


DATE_PATTERN = Pattern(
    label="DATE_TIME",
    regex=_DATE_RE,
    validator=_date_validator,
)
```

- [ ] **Step 8: Run date tests**

```bash
python -m pytest tests/unit/detector/patterns/test_date.py -v -p no:randomly
```

Expected: 8 PASSED.

- [ ] **Step 9: Register new patterns in `__init__.py`**

Replace with:

```python
from __future__ import annotations

from piighost.detector.patterns._base import Pattern
from piighost.detector.patterns.credit_card import CREDIT_CARD_PATTERN
from piighost.detector.patterns.date import DATE_PATTERN
from piighost.detector.patterns.email import EMAIL_PATTERN
from piighost.detector.patterns.iban import IBAN_PATTERN
from piighost.detector.patterns.ip import IPV4_PATTERN, IPV6_PATTERN
from piighost.detector.patterns.phone import PHONE_PATTERN
from piighost.detector.patterns.vat import VAT_PATTERN

DEFAULT_PATTERNS: list[Pattern] = [
    EMAIL_PATTERN,
    PHONE_PATTERN,
    IPV4_PATTERN,
    IPV6_PATTERN,
    CREDIT_CARD_PATTERN,
    IBAN_PATTERN,
    VAT_PATTERN,
    DATE_PATTERN,
]
```

- [ ] **Step 10: Run full detector suite**

```bash
python -m pytest tests/unit/detector/ -v -p no:randomly
```

Expected: all passing.

- [ ] **Step 11: Commit**

```bash
git add src/piighost/detector/patterns/vat.py \
        src/piighost/detector/patterns/date.py \
        src/piighost/detector/patterns/__init__.py \
        tests/unit/detector/patterns/test_vat.py \
        tests/unit/detector/patterns/test_date.py
git commit -m "feat(detector): EU_VAT and DATE_TIME patterns"
```

---

### Task 5: French NIR + German Personalausweis patterns

**Files:**
- Create: `src/piighost/detector/patterns/national_id.py`
- Modify: `src/piighost/detector/patterns/__init__.py`
- Create: `tests/unit/detector/patterns/test_national_id.py`

- [ ] **Step 1: Write failing national ID test**

Create `tests/unit/detector/patterns/test_national_id.py`:

```python
from piighost.detector.patterns.national_id import (
    FR_NIR_PATTERN,
    DE_PERSONALAUSWEIS_PATTERN,
)


def test_fr_nir_matches_valid_format():
    # 1 85 05 78 006 048 57 — known-valid NIR test number
    m = FR_NIR_PATTERN.regex.search("NIR 1850578006048 57")
    assert m is not None


def test_fr_nir_validator_accepts_valid():
    # 185057800604857 is a test-valid NIR (sex=1, year=85, month=05, dep=78, town=006, order=048, key=57)
    assert FR_NIR_PATTERN.validator("185057800604857") is True


def test_fr_nir_validator_rejects_bad_key():
    # Change key to wrong value
    assert FR_NIR_PATTERN.validator("185057800604899") is False


def test_fr_nir_validator_rejects_wrong_length():
    assert FR_NIR_PATTERN.validator("18505") is False


def test_fr_nir_label():
    assert FR_NIR_PATTERN.label == "FR_NIR"


def test_de_personalausweis_matches_format():
    m = DE_PERSONALAUSWEIS_PATTERN.regex.search("ID T22000129 valid")
    assert m is not None


def test_de_personalausweis_label():
    assert DE_PERSONALAUSWEIS_PATTERN.label == "DE_PERSONALAUSWEIS"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/detector/patterns/test_national_id.py -v -p no:randomly
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement national ID patterns**

Create `src/piighost/detector/patterns/national_id.py`:

```python
from __future__ import annotations

import re

from piighost.detector.patterns._base import Pattern

_FR_NIR_RE = re.compile(
    r"\b[12][\s]?\d{2}[\s]?(?:0[1-9]|1[0-2])[\s]?"
    r"(?:\d{2}|2[AB])[\s]?\d{3}[\s]?\d{3}[\s]?\d{2}\b"
)


def _fr_nir_validator(text: str) -> bool:
    normalized = "".join(c for c in text if c.isdigit() or c in "AB")
    if len(normalized) != 15:
        return False
    body = normalized[:13]
    key_str = normalized[13:]
    body_numeric = body.replace("2A", "19").replace("2B", "18")
    try:
        body_int = int(body_numeric)
        key = int(key_str)
    except ValueError:
        return False
    expected_key = 97 - (body_int % 97)
    return expected_key == key


_DE_ID_RE = re.compile(r"\b[A-Z]\d{8}\b")


DE_PERSONALAUSWEIS_PATTERN = Pattern(
    label="DE_PERSONALAUSWEIS",
    regex=_DE_ID_RE,
)

FR_NIR_PATTERN = Pattern(
    label="FR_NIR",
    regex=_FR_NIR_RE,
    validator=_fr_nir_validator,
)
```

- [ ] **Step 4: Run national ID tests**

```bash
python -m pytest tests/unit/detector/patterns/test_national_id.py -v -p no:randomly
```

Expected: 7 PASSED. If the French NIR key validation fails, double-check the test vector — use a known-valid NIR from https://en.wikipedia.org/wiki/INSEE_code examples, recompute by hand, and adjust both the test fixture and the expected key.

- [ ] **Step 5: Register new patterns in `__init__.py`**

Replace with:

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
)
from piighost.detector.patterns.phone import PHONE_PATTERN
from piighost.detector.patterns.vat import VAT_PATTERN

DEFAULT_PATTERNS: list[Pattern] = [
    EMAIL_PATTERN,
    PHONE_PATTERN,
    IPV4_PATTERN,
    IPV6_PATTERN,
    CREDIT_CARD_PATTERN,
    IBAN_PATTERN,
    VAT_PATTERN,
    DATE_PATTERN,
    FR_NIR_PATTERN,
    DE_PERSONALAUSWEIS_PATTERN,
]
```

- [ ] **Step 6: Run full detector suite**

```bash
python -m pytest tests/unit/detector/ -v -p no:randomly
```

Expected: all passing.

- [ ] **Step 7: Commit**

```bash
git add src/piighost/detector/patterns/national_id.py \
        src/piighost/detector/patterns/__init__.py \
        tests/unit/detector/patterns/test_national_id.py
git commit -m "feat(detector): FR_NIR (key validation) and DE_PERSONALAUSWEIS patterns"
```

---

### Task 6: Wire `regex_only` backend in `_build_default_detector`

**Files:**
- Modify: `src/piighost/service/core.py`
- Create: `tests/unit/test_detector_wiring.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_detector_wiring.py`:

```python
import asyncio
from piighost.service.config import ServiceConfig, DetectorSection
from piighost.service.core import _build_default_detector
from piighost.detector.regex import RegexDetector


def test_regex_only_backend_returns_regex_detector():
    config = ServiceConfig(detector=DetectorSection(backend="regex_only"))
    detector = asyncio.run(_build_default_detector(config))
    assert isinstance(detector, RegexDetector)


def test_regex_detector_detects_email():
    config = ServiceConfig(detector=DetectorSection(backend="regex_only"))
    detector = asyncio.run(_build_default_detector(config))
    detections = asyncio.run(detector.detect("contact alice@example.com"))
    assert any(d.label == "EMAIL_ADDRESS" for d in detections)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/test_detector_wiring.py -v -p no:randomly
```

Expected: `NotImplementedError: detector backend 'regex_only' not shipped yet`.

- [ ] **Step 3: Update `_build_default_detector` in `src/piighost/service/core.py`**

Read the existing function first. It currently looks like:

```python
async def _build_default_detector(config: ServiceConfig) -> _Detector:
    import os
    if os.environ.get("PIIGHOST_DETECTOR") == "stub":
        return _StubDetector()
    if config.detector.backend == "gliner2":
        from gliner2 import GLiNER2
        from piighost.detector.gliner2 import Gliner2Detector
        model = GLiNER2.from_pretrained(config.detector.gliner2_model)
        return Gliner2Detector(model=model, labels=config.detector.labels)
    raise NotImplementedError(
        f"detector backend {config.detector.backend!r} not shipped yet"
    )
```

Add a branch for `regex_only` before the `raise`:

```python
    if config.detector.backend == "regex_only":
        from piighost.detector.regex import RegexDetector
        return RegexDetector()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/unit/test_detector_wiring.py -v -p no:randomly
```

Expected: 2 PASSED.

- [ ] **Step 5: Run full unit suite**

```bash
python -m pytest tests/unit/ -q -p no:randomly 2>&1 | tail -5
```

Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add src/piighost/service/core.py tests/unit/test_detector_wiring.py
git commit -m "feat(service): wire regex_only backend to RegexDetector"
```

---

### Task 7: MCP `vault_list` reveal propagation

**Files:**
- Modify: `src/piighost/mcp/server.py`
- Create: `tests/unit/test_mcp_reveal.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_mcp_reveal.py`:

```python
import asyncio
import pytest
from pathlib import Path


@pytest.fixture()
def mcp_with_vault(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    from piighost.mcp.server import build_mcp

    vault_dir = tmp_path / "vault"
    mcp, svc = asyncio.run(build_mcp(vault_dir))
    # Seed the vault with one entity via anonymize
    asyncio.run(svc.anonymize("Alice lives in Paris"))
    yield mcp, svc
    asyncio.run(svc.close())


def test_vault_list_reveal_false_masks_original(mcp_with_vault):
    mcp, _ = mcp_with_vault
    tools = asyncio.run(mcp.get_tools())
    vault_list_tool = tools["vault_list"]
    # FastMCP tool call — use run() or the internal callable
    result = asyncio.run(vault_list_tool.run({"reveal": False}))
    entries = result.content if hasattr(result, "content") else result
    # Each entry should have original=None when reveal=False
    for e in entries:
        payload = e if isinstance(e, dict) else e.model_dump()
        assert payload.get("original") is None


def test_vault_list_reveal_true_surfaces_original(mcp_with_vault):
    mcp, _ = mcp_with_vault
    tools = asyncio.run(mcp.get_tools())
    vault_list_tool = tools["vault_list"]
    result = asyncio.run(vault_list_tool.run({"reveal": True}))
    entries = result.content if hasattr(result, "content") else result
    # At least one entry should have a non-None original
    has_original = False
    for e in entries:
        payload = e if isinstance(e, dict) else e.model_dump()
        if payload.get("original") is not None:
            has_original = True
            break
    assert has_original, "reveal=True should populate at least one original field"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/test_mcp_reveal.py -v -p no:randomly
```

Expected: `test_vault_list_reveal_true_surfaces_original` FAILS — `original` is still `None` because `vault_list` hardcodes `reveal=False`.

NOTE: If the FastMCP tool `.run({...})` API doesn't match this signature on the installed version, use the same call pattern the existing `tests/unit/test_mcp_server.py` uses. Read that test file to see how the MCP tools are invoked.

- [ ] **Step 3: Fix `vault_list` in `src/piighost/mcp/server.py`**

Find the `vault_list` tool definition (line 43-46 currently) and change it to accept and propagate `reveal`:

```python
    @mcp.tool(description="List vault entries with optional label filter")
    async def vault_list(
        label: str = "",
        limit: int = 100,
        offset: int = 0,
        reveal: bool = False,
    ) -> list[dict]:
        page = await svc.vault_list(
            label=label or None, limit=limit, offset=offset, reveal=reveal
        )
        return [e.model_dump(exclude_none=False) for e in page.entries]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/unit/test_mcp_reveal.py -v -p no:randomly
```

Expected: 2 PASSED.

- [ ] **Step 5: Run full unit suite**

```bash
python -m pytest tests/unit/ -q -p no:randomly 2>&1 | tail -5
```

Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add src/piighost/mcp/server.py tests/unit/test_mcp_reveal.py
git commit -m "fix(mcp): vault_list propagates reveal parameter instead of hardcoded False"
```

---

### Task 8: `MistralEmbedder` API key validation at construction

**Files:**
- Modify: `src/piighost/indexer/embedder.py`
- Create: `tests/unit/indexer/test_mistral_embedder.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/indexer/test_mistral_embedder.py`:

```python
import pytest
from piighost.indexer.embedder import MistralEmbedder, build_embedder
from piighost.service.config import EmbedderSection


def test_mistral_embedder_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("PIIGHOST_EMBEDDER", raising=False)
    with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
        build_embedder(EmbedderSection(backend="mistral"))


def test_mistral_embedder_accepts_api_key(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    monkeypatch.delenv("PIIGHOST_EMBEDDER", raising=False)
    embedder = build_embedder(EmbedderSection(backend="mistral"))
    assert isinstance(embedder, MistralEmbedder)


def test_stub_override_wins_even_without_mistral_key(monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    embedder = build_embedder(EmbedderSection(backend="mistral"))
    # Stub override returns _StubEmbedder regardless of backend
    assert embedder.__class__.__name__ == "_StubEmbedder"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/indexer/test_mistral_embedder.py -v -p no:randomly
```

Expected: `test_mistral_embedder_raises_without_api_key` FAILS — current code silently constructs `MistralEmbedder` with an empty API key (it reads from env at request time).

- [ ] **Step 3: Update `build_embedder` in `src/piighost/indexer/embedder.py`**

Find the `build_embedder` function (currently at the bottom of the file). Update the `mistral` branch to validate the API key:

```python
def build_embedder(cfg: EmbedderSection) -> AnyEmbedder:
    if os.environ.get("PIIGHOST_EMBEDDER") == "stub":
        return _StubEmbedder()
    if cfg.backend == "none":
        return NullEmbedder()
    if cfg.backend == "local":
        return LocalEmbedder(cfg.local_model)
    if cfg.backend == "mistral":
        if not os.environ.get("MISTRAL_API_KEY"):
            raise RuntimeError("MISTRAL_API_KEY not set for mistral embedder")
        return MistralEmbedder(cfg.mistral_model)
    raise ValueError(f"Unknown embedder backend: {cfg.backend!r}")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/unit/indexer/test_mistral_embedder.py -v -p no:randomly
```

Expected: 3 PASSED.

- [ ] **Step 5: Run full unit + E2E suite**

```bash
python -m pytest tests/unit/ tests/e2e/ -q -p no:randomly 2>&1 | tail -5
```

Expected: all passing (E2E suite already uses `monkeypatch.setenv("MISTRAL_API_KEY", "test-key")` in the PII-zero-leak test, so no regression).

- [ ] **Step 6: Commit**

```bash
git add src/piighost/indexer/embedder.py tests/unit/indexer/test_mistral_embedder.py
git commit -m "fix(indexer): MistralEmbedder fails fast when MISTRAL_API_KEY missing"
```

---

## Self-Review

### Spec coverage

| Spec requirement | Task(s) |
|------------------|---------|
| `regex_only` detector end `NotImplementedError` | Task 6 |
| `Pattern` dataclass | Task 1 |
| EMAIL_ADDRESS | Task 1 |
| PHONE_NUMBER | Task 2 |
| IP_ADDRESS (v4 + v6) | Task 2 |
| CREDIT_CARD with Luhn | Task 3 |
| IBAN_CODE with mod-97 | Task 3 |
| EU_VAT | Task 4 |
| DATE_TIME | Task 4 |
| FR_NIR with key validation | Task 5 |
| DE_PERSONALAUSWEIS | Task 5 |
| `RegexDetector` iterates patterns + validates + overlaps | Task 1 |
| `_build_default_detector` routes `regex_only` | Task 6 |
| MCP `reveal` propagation (vault_list) | Task 7 |
| MistralEmbedder `MISTRAL_API_KEY` validation | Task 8 |
| PII-zero-leak invariant preserved | Already covered by existing Sprint 2 test; Task 8 verifies no regression |

### Placeholder scan

- No "TBD", "TODO", or vague requirements.
- All code blocks are complete.
- Each test step shows the exact test code to write.

### Type consistency

- `Pattern` dataclass defined once in Task 1, used unchanged in every pattern module (Tasks 1-5).
- `DEFAULT_PATTERNS` list grows cumulatively across Tasks 1-5, final state shown in Task 5.
- `RegexDetector.detect` signature consistent across Task 1 (defined) and Task 6 (used).
- Labels are consistent: `EMAIL_ADDRESS`, `PHONE_NUMBER`, `IP_ADDRESS`, `CREDIT_CARD`, `IBAN_CODE`, `EU_VAT`, `DATE_TIME`, `FR_NIR`, `DE_PERSONALAUSWEIS` — all match the spec Section 2.2 table.
- `vault_list` MCP tool signature: new `reveal: bool = False` parameter added in Task 7, matches the existing service method signature.
- `build_embedder(cfg: EmbedderSection) -> AnyEmbedder` signature unchanged in Task 8 — only body changed.

All type/name consistency checks pass.
