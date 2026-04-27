# RGPD Phase 4 — Wizard `/hacienda:setup` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the conversational onboarding wizard `/hacienda:setup` so a new avocat/notaire/EC/médecin/RH user fills out their controller profile in 6 steps and ends up with a valid `~/.piighost/controller.toml` driving every downstream RGPD tool. Also adds the bundled per-profession default-profile TOMLs (originally Phase 0 spec scope, never implemented) and a new `controller_profile_defaults` MCP method so the wizard can pre-fill sensible answers.

**Architecture:** Static TOML defaults bundled at `src/piighost/compliance/profiles/<profession>.toml`. Daemon exposes a read-only `controller_profile_defaults(profession)` MCP method that loads and returns the bundled TOML for one profession. The wizard itself is a plugin skill (`/hacienda:setup`) — pure markdown that orchestrates a 6-step conversational flow via existing MCP tools (`controller_profile_get`, `controller_profile_defaults`, `controller_profile_set`). Mode switching: bare `/hacienda:setup` writes the global profile; `/hacienda:setup --project <name>` writes a per-project override.

**Tech Stack:** Python 3.13 stdlib `tomllib`, FastMCP shim, existing `ControllerProfileService` (Phase 0). Plugin skills are markdown-only — no new code in the plugin worktree.

**Spec:** `docs/superpowers/specs/2026-04-27-rgpd-compliance-design.md` (commit `a2535c3`), section "Wizard `/hacienda:setup`" (lines 590–616) + the bundled `compliance/profiles/` row in the file map (line 696, marked Phase 0 but never landed).

**Phase 0–2 prerequisites (already merged at `63e8dbd`):**
- `ControllerProfileService.{get,set,has_global}` (Phase 0 commit `eaff703`)
- `controller_profile_get/set` MCP tools (Phase 2 Task 2, commit `f6944f5`)
- `processing_register` / `dpia_screening` / `render_compliance_doc` (Phase 2)

**Phase 3 status:** No "Phase 3" was ever written — the spec uses Phase numbers 0/1/2/Wizard, and the codebase shipped them as 0/1/2/4 to leave room. This plan is the Wizard phase, labelled Phase 4 for clarity.

**Project root for all paths below:** `C:\Users\NMarchitecte\Documents\piighost`. The plugin worktree is at `.worktrees/hacienda-plugin` (separate git, branch `main`).

**Branch:** all backend work commits to `master` in the piighost repo. Plugin commits to `main` in the plugin worktree. Each task ends with a commit; final push at end of phase.

---

## Decisions verrouillées (carried from spec brainstorming)

- **Bundled defaults shipped, not auto-fetched.** No remote fetching of CNIL/CNB updates — the bundled TOMLs are the single source of truth, version-controlled.
- **Wizard is a skill, not a Python CLI.** The skill orchestrates MCP calls; the model handles the conversational flow. This keeps the surface lean and lets users override any answer interactively.
- **`controller_profile_defaults` is read-only.** A separate MCP method (not a `controller_profile_get` flag) so the FastMCP signature stays simple — one method, one purpose.
- **Per-project override mode preserves global as base.** `--project <name>` mode loads the global profile, asks ONLY the override fields, writes a per-project TOML containing only the diffs.
- **Profession-driven prefill, user-driven final answers.** The defaults pre-populate `finalites`, `bases_legales`, `duree_conservation_apres_fin_mission`, suggested DPO obligation flag, and ordinal-number label. The wizard surfaces them for review — the user can accept, edit, or replace.

---

## File map (Phase 4)

| Path | Type | Owns |
|---|---|---|
| `src/piighost/compliance/profiles/avocat.toml` | new | Avocat defaults (CNB, secret pro Art. 66-5) |
| `src/piighost/compliance/profiles/notaire.toml` | new | Notaire defaults (CSN, Art. 1316-2 Code civil) |
| `src/piighost/compliance/profiles/medecin.toml` | new | Médecin defaults (Art. R4127, HDS) |
| `src/piighost/compliance/profiles/expert_comptable.toml` | new | EC defaults (OEC, Code de déontologie 2012) |
| `src/piighost/compliance/profiles/rh.toml` | new | RH defaults (Code du travail, durée 5 ans après départ) |
| `src/piighost/compliance/profiles/generic.toml` | new | Generic defaults (catch-all) |
| `src/piighost/compliance/profile_loader.py` | new | `load_bundled_profile(profession)` — pure function |
| `src/piighost/service/core.py` | modify | `controller_profile_defaults` dispatcher + per-service method |
| `src/piighost/mcp/tools.py` | modify | 1 new ToolSpec (`controller_profile_defaults`) |
| `src/piighost/mcp/shim.py` | modify | 1 new `@mcp.tool` wrapper |
| `src/piighost/daemon/server.py` | modify | 1 new dispatch handler |
| `tests/unit/test_profile_loader.py` | new | Loads each bundled profile, asserts shape |
| `tests/unit/test_controller_profile_defaults_mcp.py` | new | Service-level test for the MCP method |
| `.worktrees/hacienda-plugin/skills/setup/SKILL.md` | new | The `/hacienda:setup` skill itself |
| `.worktrees/hacienda-plugin/.claude-plugin/plugin.json` | modify | Bump v0.6.0 → v0.7.0 |
| `docs/superpowers/followups/2026-04-27-rgpd-phase4-followups.md` | new | Phase 4 follow-up issues (created during Task 7 if any) |

---

## Task 1: Bundled profession profile TOMLs

**Files:**
- Create: `src/piighost/compliance/profiles/avocat.toml`
- Create: `src/piighost/compliance/profiles/notaire.toml`
- Create: `src/piighost/compliance/profiles/medecin.toml`
- Create: `src/piighost/compliance/profiles/expert_comptable.toml`
- Create: `src/piighost/compliance/profiles/rh.toml`
- Create: `src/piighost/compliance/profiles/generic.toml`

These are static defaults — no code, just well-curated TOML the wizard pre-loads when the user picks a profession.

- [ ] **Step 1: Create the directory**

```bash
mkdir -p src/piighost/compliance/profiles
```

- [ ] **Step 2: Write `avocat.toml`**

```toml
# Default profile for cabinets d'avocats (France).
# Loaded by the /hacienda:setup wizard when profession="avocat".
# Source: CNB / loi du 31 décembre 1971 (Art. 66-5) / RIN.

[controller]
profession = "avocat"
country = "FR"
ordinal_label = "Numéro de barreau (CNB)"

[dpo]
required_hint = "obligatoire si traitement à grande échelle de données sensibles ou si autorité publique"

[defaults]
finalites = [
    "Conseil et représentation juridique",
    "Gestion du dossier client (secret professionnel Art. 66-5)",
    "Facturation et comptabilité",
]
bases_legales = [
    "execution_contrat",
    "obligation_legale",
]
duree_conservation_apres_fin_mission = "5 ans (prescription civile Art. 2224 Code civil) — 10 ans pour pièces comptables"
mentions_legales_url = "https://www.cnb.avocat.fr/"

[suggested_security_measures]
items = [
    "Chiffrement au repos (vault piighost SQLite + LanceDB)",
    "Détection PII locale (pas de transfert vers cloud externe pour inférence)",
    "Cloisonnement par dossier (un projet piighost par client)",
    "Authentification renforcée poste de travail",
    "Sauvegarde chiffrée hors-site",
]
```

- [ ] **Step 3: Write `notaire.toml`**

```toml
# Default profile for offices notariaux (France).
# Source: Conseil Supérieur du Notariat / Décret 71-941 / Art. 1316-2 Code civil.

[controller]
profession = "notaire"
country = "FR"
ordinal_label = "Numéro de chambre départementale (CSN)"

[dpo]
required_hint = "souvent obligatoire — patrimoines, identités, généalogie sur grande échelle"

[defaults]
finalites = [
    "Authentification d'actes (immobilier, succession, contrat de mariage)",
    "Conseil patrimonial et fiscal",
    "Conservation des minutes (obligation légale)",
    "Facturation et comptabilité",
]
bases_legales = [
    "obligation_legale",
    "execution_contrat",
]
duree_conservation_apres_fin_mission = "75 ans (minutes) — 10 ans (pièces comptables) — 5 ans (correspondance)"
mentions_legales_url = "https://www.notaires.fr/"

[suggested_security_measures]
items = [
    "Chiffrement au repos",
    "Détection PII locale",
    "Conservation des minutes en coffre numérique notarial (Minutier Central Électronique)",
    "Authentification renforcée poste de travail",
    "Sauvegarde chiffrée hors-site",
]
```

- [ ] **Step 4: Write `medecin.toml`**

```toml
# Default profile for cabinets médicaux (France).
# Source: Code de la santé publique (Art. R4127) / Conseil de l'Ordre / HDS.

[controller]
profession = "medecin"
country = "FR"
ordinal_label = "Numéro RPPS / ADELI"

[dpo]
required_hint = "obligatoire — données de santé Art. 9 traitées systématiquement"

[defaults]
finalites = [
    "Tenue du dossier médical patient (Art. R1112-2 CSP)",
    "Facturation et téléconsultation",
    "Suivi médical et continuité des soins",
]
bases_legales = [
    "consentement_explicite",
    "interet_vital",
    "mission_interet_public_sante",
]
duree_conservation_apres_fin_mission = "20 ans après dernier passage (Art. R1112-7 CSP) — 10 ans après le décès"
mentions_legales_url = "https://www.conseil-national.medecin.fr/"

[suggested_security_measures]
items = [
    "Hébergement HDS (Hébergeur de Données de Santé) certifié",
    "Chiffrement au repos + en transit",
    "Authentification forte (CPS / e-CPS)",
    "Détection PII locale (aucun transfert hors UE)",
    "Cloisonnement par patient",
    "Audit log immuable",
]
```

- [ ] **Step 5: Write `expert_comptable.toml`**

```toml
# Default profile for cabinets d'expertise comptable (France).
# Source: Ordre des Experts-Comptables (OEC) / Code de déontologie 2012.

[controller]
profession = "expert_comptable"
country = "FR"
ordinal_label = "Numéro d'inscription au tableau de l'OEC"

[dpo]
required_hint = "souvent recommandé — traitement à grande échelle de données sociales et fiscales"

[defaults]
finalites = [
    "Tenue de comptabilité et déclarations fiscales",
    "Audit légal et révision des comptes",
    "Conseil en gestion sociale (paie, déclarations sociales)",
    "Facturation et secret professionnel comptable",
]
bases_legales = [
    "execution_contrat",
    "obligation_legale",
]
duree_conservation_apres_fin_mission = "10 ans (pièces comptables Art. L123-22 Code de commerce) — 6 ans (pièces fiscales L102B LPF)"
mentions_legales_url = "https://www.experts-comptables.fr/"

[suggested_security_measures]
items = [
    "Chiffrement au repos",
    "Détection PII locale",
    "Cloisonnement par client",
    "Authentification renforcée",
    "Sauvegarde chiffrée hors-site",
]
```

- [ ] **Step 6: Write `rh.toml`**

```toml
# Default profile for services Ressources Humaines (France).
# Source: Code du travail / CNIL "Pack RH".

[controller]
profession = "rh"
country = "FR"
ordinal_label = ""  # RH = service interne, pas d'inscription ordinale

[dpo]
required_hint = "obligatoire au-delà de 250 salariés ou si profilage / décisions automatisées"

[defaults]
finalites = [
    "Gestion administrative du personnel",
    "Paie et déclarations sociales",
    "Recrutement",
    "Évaluation et formation",
]
bases_legales = [
    "execution_contrat",
    "obligation_legale",
]
duree_conservation_apres_fin_mission = "5 ans après départ (dossier) — 5 ans (paie L3243-4) — 2 ans (recrutement non retenu) — 5 ans (CV reçus avec consentement)"
mentions_legales_url = "https://www.cnil.fr/fr/la-gestion-des-ressources-humaines"

[suggested_security_measures]
items = [
    "Chiffrement au repos",
    "Détection PII locale",
    "Cloisonnement par salarié",
    "Authentification renforcée",
    "Habilitations strictes (RH ≠ manager ≠ paie)",
    "Audit log immuable",
]
```

- [ ] **Step 7: Write `generic.toml`**

```toml
# Catch-all default profile for users who don't match a specific profession.
# Loaded when profession="generic" or unknown.

[controller]
profession = "generic"
country = "FR"
ordinal_label = ""

[dpo]
required_hint = "à évaluer selon Art. 37 RGPD (autorité publique / surveillance systématique / Art. 9-10 à grande échelle)"

[defaults]
finalites = [
    "Gestion du dossier client",
    "Facturation",
]
bases_legales = [
    "execution_contrat",
]
duree_conservation_apres_fin_mission = "À déterminer selon la nature du traitement (Art. 5.1.e RGPD — limitation de la conservation)"
mentions_legales_url = ""

[suggested_security_measures]
items = [
    "Chiffrement au repos",
    "Détection PII locale",
    "Authentification renforcée",
]
```

- [ ] **Step 8: Verify the files load as TOML**

```
PYTHONPATH=src .venv/Scripts/python.exe -c "
import tomllib
from pathlib import Path
root = Path('src/piighost/compliance/profiles')
for f in sorted(root.glob('*.toml')):
    data = tomllib.loads(f.read_text(encoding='utf-8'))
    assert 'controller' in data and 'defaults' in data, f
    print(f.stem, 'OK', list(data.keys()))
"
```
Expected: 6 lines, one per profile, each with `controller` + `defaults` + `dpo` + `suggested_security_measures` keys.

- [ ] **Step 9: Commit**

```bash
git add src/piighost/compliance/profiles/
git commit -m "feat(compliance): bundled per-profession default profiles

Six TOML files under src/piighost/compliance/profiles/ with sensible
defaults the /hacienda:setup wizard pre-loads when the user picks a
profession:

  - avocat        — CNB / Art. 66-5 / 5–10 ans
  - notaire       — CSN / Art. 1316-2 / 75 ans (minutes)
  - medecin       — RPPS / Art. R1112-7 / 20 ans après dernier passage
  - expert_comptable — OEC / L123-22 / 10 ans
  - rh            — Code du travail / CNIL Pack RH / 5 ans après départ
  - generic       — catch-all

Spec: docs/superpowers/specs/2026-04-27-rgpd-compliance-design.md
section 'Wizard /hacienda:setup'."
```

---

## Task 2: `profile_loader` module

**Files:**
- Create: `src/piighost/compliance/profile_loader.py`
- Test: `tests/unit/test_profile_loader.py`

Pure function `load_bundled_profile(profession: str) -> dict` that reads the TOML at `piighost/compliance/profiles/<profession>.toml` via `importlib.resources`. Returns `{}` on unknown profession. No I/O outside the package.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the bundled profession profile loader."""
from __future__ import annotations

import pytest

from piighost.compliance.profile_loader import load_bundled_profile


def test_load_avocat_profile():
    profile = load_bundled_profile("avocat")
    assert profile["controller"]["profession"] == "avocat"
    assert "Conseil et représentation juridique" in profile["defaults"]["finalites"]


def test_load_each_profession_returns_controller_and_defaults():
    for prof in ("avocat", "notaire", "medecin", "expert_comptable", "rh", "generic"):
        profile = load_bundled_profile(prof)
        assert "controller" in profile, prof
        assert "defaults" in profile, prof
        assert profile["controller"]["profession"] == prof


def test_load_unknown_profession_returns_empty_dict():
    assert load_bundled_profile("zorblax") == {}


def test_load_rejects_path_traversal():
    """profession is user-input — must not escape the bundled dir."""
    assert load_bundled_profile("../etc/passwd") == {}
    assert load_bundled_profile("avocat/../../etc") == {}


def test_load_rejects_empty_string():
    assert load_bundled_profile("") == {}
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_profile_loader.py -v --no-header
```
Expected: ImportError on `piighost.compliance.profile_loader`.

- [ ] **Step 3: Implement `profile_loader.py`**

Create `src/piighost/compliance/profile_loader.py`:

```python
"""Load bundled per-profession default profiles for the /hacienda:setup wizard.

Profile TOMLs live under ``piighost.compliance.profiles/<profession>.toml`` and
ship in the wheel. The loader is read-only and never touches user files.
"""
from __future__ import annotations

import re
import sys
from importlib import resources

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


_PROFESSION_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def load_bundled_profile(profession: str) -> dict:
    """Return the bundled default profile for *profession*, or ``{}`` if
    the profession is unknown or the input fails validation.

    The validation regex blocks path traversal — *profession* is reachable
    from the MCP boundary (untrusted).
    """
    if not _PROFESSION_RE.match(profession or ""):
        return {}
    try:
        path = resources.files("piighost.compliance.profiles") / f"{profession}.toml"
        if not path.is_file():
            return {}
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, AttributeError, tomllib.TOMLDecodeError, OSError):
        return {}
```

- [ ] **Step 4: Run tests to verify they pass**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_profile_loader.py -v --no-header
```
Expected: 5 passed.

- [ ] **Step 5: Verify package data ships in wheel**

Hatchling's `[tool.hatch.build.targets.wheel]` already includes everything under `src/piighost/`. No `pyproject.toml` change needed (mirrors how Phase 2 templates ship). Verify the file list at runtime:

```
PYTHONPATH=src .venv/Scripts/python.exe -c "
from importlib import resources
files = sorted(p.name for p in resources.files('piighost.compliance.profiles').iterdir() if p.suffix == '.toml')
print(files)
assert len(files) == 6, files
"
```
Expected: `['avocat.toml', 'expert_comptable.toml', 'generic.toml', 'medecin.toml', 'notaire.toml', 'rh.toml']`.

- [ ] **Step 6: Commit**

```bash
git add src/piighost/compliance/profile_loader.py tests/unit/test_profile_loader.py
git commit -m "feat(compliance): profile_loader for bundled profession defaults

load_bundled_profile(profession) reads the bundled TOML at
piighost.compliance.profiles/<profession>.toml via importlib.resources.

Validates profession against ^[a-z][a-z0-9_]{0,31}\$ to block path
traversal — input is reachable from the MCP boundary (untrusted).
Returns {} for unknown profession or invalid input."
```

---

## Task 3: Service method `controller_profile_defaults` + dispatcher

**Files:**
- Modify: `src/piighost/service/core.py` (add per-service method + PIIGhostService dispatcher)
- Test: `tests/unit/test_controller_profile_defaults_mcp.py`

The service method just wraps `load_bundled_profile`. There's nothing async or stateful here, but we keep the `async def` shape to match the MCP boundary convention.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_controller_profile_defaults_mcp.py`:

```python
"""Service-level test for controller_profile_defaults MCP dispatcher."""
from __future__ import annotations

import asyncio

import pytest

from piighost.service.config import ServiceConfig, RerankerSection
from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    cfg = ServiceConfig(reranker=RerankerSection(backend="none"))
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))


def test_controller_profile_defaults_returns_avocat(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    profile = asyncio.run(svc.controller_profile_defaults(profession="avocat"))
    assert profile["controller"]["profession"] == "avocat"
    assert "finalites" in profile["defaults"]
    asyncio.run(svc.close())


def test_controller_profile_defaults_unknown_returns_empty(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    profile = asyncio.run(svc.controller_profile_defaults(profession="zorblax"))
    assert profile == {}
    asyncio.run(svc.close())


def test_controller_profile_defaults_rejects_path_traversal(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    profile = asyncio.run(svc.controller_profile_defaults(profession="../etc/passwd"))
    assert profile == {}
    asyncio.run(svc.close())


def test_controller_profile_defaults_each_profession(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    for prof in ("avocat", "notaire", "medecin", "expert_comptable", "rh", "generic"):
        profile = asyncio.run(svc.controller_profile_defaults(profession=prof))
        assert profile.get("controller", {}).get("profession") == prof, prof
    asyncio.run(svc.close())
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_controller_profile_defaults_mcp.py -v --no-header
```
Expected: AttributeError on `controller_profile_defaults`.

- [ ] **Step 3: Add the method to `PIIGhostService`**

In `src/piighost/service/core.py`, locate the existing `async def controller_profile_get(...)` method (around line 1301) and add immediately before or after it:

```python
    async def controller_profile_defaults(self, *, profession: str) -> dict:
        """Return the bundled default profile for *profession*, or {} if unknown.

        Read-only, never touches the user's controller.toml. Used by the
        /hacienda:setup wizard to pre-fill answers.
        """
        from piighost.compliance.profile_loader import load_bundled_profile
        return load_bundled_profile(profession)
```

- [ ] **Step 4: Run tests to verify they pass**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_controller_profile_defaults_mcp.py -v --no-header
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/service/core.py tests/unit/test_controller_profile_defaults_mcp.py
git commit -m "feat(service): controller_profile_defaults for /hacienda:setup wizard

Read-only PIIGhostService.controller_profile_defaults(profession) returns
the bundled default profile for a given profession. Wraps the
profile_loader.load_bundled_profile pure function.

Used by the /hacienda:setup skill to pre-fill answers (finalites,
bases_legales, duree_conservation, ordinal_label) when the user picks
their profession."
```

---

## Task 4: MCP wiring for `controller_profile_defaults`

**Files:**
- Modify: `src/piighost/mcp/tools.py` (1 ToolSpec)
- Modify: `src/piighost/mcp/shim.py` (1 wrapper)
- Modify: `src/piighost/daemon/server.py` (1 dispatch handler)

Mirrors the wiring pattern used for `controller_profile_get/set` (Phase 2 Task 2, commit `f6944f5`).

- [ ] **Step 1: Add the ToolSpec**

In `src/piighost/mcp/tools.py`, find the existing `controller_profile_get` and `controller_profile_set` ToolSpec entries (under the `# Controller profile` comment block). Append:

```python
    ToolSpec(
        name="controller_profile_defaults",
        rpc_method="controller_profile_defaults",
        description=(
            "Read-only: return the bundled default profile for a profession "
            "(avocat / notaire / medecin / expert_comptable / rh / generic). "
            "Used by /hacienda:setup to pre-fill finalites, bases_legales, "
            "duree_conservation, and ordinal_label. Returns {} for unknown "
            "profession."
        ),
        timeout_s=2.0,
    ),
```

- [ ] **Step 2: Add the shim wrapper**

In `src/piighost/mcp/shim.py`, find the existing controller-profile wrappers in `_build_mcp` and add right after them:

```python
    @mcp.tool(name="controller_profile_defaults",
              description=by_name["controller_profile_defaults"].description)
    async def controller_profile_defaults(profession: str) -> dict:
        return await _lazy_dispatch(
            by_name["controller_profile_defaults"],
            params={"profession": profession},
        )
```

(If your codebase uses `forward_to_daemon` or a different primitive than `_lazy_dispatch`, mirror what the existing `controller_profile_get` wrapper uses — they must be consistent.)

- [ ] **Step 3: Add the dispatch handler**

In `src/piighost/daemon/server.py`'s `_dispatch` function, immediately after the `controller_profile_set` branch (around line 343):

```python
    if method == "controller_profile_defaults":
        return await svc.controller_profile_defaults(
            profession=params["profession"],
        )
```

- [ ] **Step 4: Smoke test the registration**

```
PYTHONPATH=src .venv/Scripts/python.exe -c "
from piighost.mcp.tools import TOOL_CATALOG
names = [t.name for t in TOOL_CATALOG]
assert 'controller_profile_defaults' in names
print('controller_profile_defaults registered')
"
```
Expected: `controller_profile_defaults registered`.

- [ ] **Step 5: Re-run all controller-profile + defaults tests**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_controller_profile_mcp.py tests/unit/test_controller_profile_defaults_mcp.py tests/unit/test_profile_loader.py -v --no-header
```
Expected: all green (existing 4 + new 4 + 5 = 13).

- [ ] **Step 6: Commit**

```bash
git add src/piighost/mcp/tools.py src/piighost/mcp/shim.py src/piighost/daemon/server.py
git commit -m "feat(mcp): wire controller_profile_defaults

One new MCP tool: controller_profile_defaults(profession) -> dict.
Read-only, 2s timeout (just a TOML read from the wheel).

Used by /hacienda:setup to pre-fill profession-driven defaults
without round-tripping through controller.toml."
```

---

## Task 5: `/hacienda:setup` skill (global mode)

**Files:**
- Create: `.worktrees/hacienda-plugin/skills/setup/SKILL.md`

The skill is markdown — orchestrates the 6-step conversational flow via MCP calls. Bare `/hacienda:setup` writes the global profile.

The Cowork plugin worktree lives at `.worktrees/hacienda-plugin` with its own `.git` (branch `main`). All `git -C ...` commands target that worktree.

- [ ] **Step 1: Create the skill directory + SKILL.md**

```bash
mkdir -p .worktrees/hacienda-plugin/skills/setup
```

Create `.worktrees/hacienda-plugin/skills/setup/SKILL.md`:

```markdown
---
name: setup
description: Onboarding wizard for the hacienda plugin. Walks the avocat / notaire / EC / médecin / RH user through a 6-step conversational setup of their RGPD controller profile (cabinet identity, ordinal number, DPO, finalités, durée de conservation). Auto-loads profession-specific defaults from the bundled profiles. Writes ~/.piighost/controller.toml. Triggers on /hacienda:setup, on a fresh install, or when any other RGPD tool detects an empty controller profile.
argument-hint: "[--project <name>]"
---

# /hacienda:setup — Wizard d'onboarding RGPD

```
/hacienda:setup
/hacienda:setup --project <name>
```

This wizard walks the user through 6 steps to fill in the controller profile that drives every downstream RGPD tool (`processing_register`, `dpia_screening`, `render_compliance_doc`, `subject_access`, `forget_subject`).

## Mode detection

- **Bare `/hacienda:setup`** → global mode. Writes `~/.piighost/controller.toml`. Run on first install.
- **`/hacienda:setup --project <name>`** → per-project override mode (Task 6 of the plan adds this — see the `--project` section below). Loads global, asks ONLY the override fields, writes `~/.piighost/projects/<name>/controller_overrides.toml`.

## Pre-flight check

Call `mcp__piighost__controller_profile_get(scope="global")`.

- If the result is **non-empty** and the user invoked the bare command, ask whether they want to (a) overwrite, (b) edit one specific section, or (c) cancel. Default to (b).
- If empty (or the user chose overwrite), proceed with the 6-step flow below.

## Step 1 — Profession

Ask: "Quelle est votre profession ?"

Choices: `avocat` / `notaire` / `expert_comptable` / `medecin` / `rh` / `autre` (→ `generic`).

Capture the answer as `<profession>`. Immediately call:

```
mcp__piighost__controller_profile_defaults(profession="<profession>")
```

This returns a dict with `controller.ordinal_label`, `dpo.required_hint`, `defaults.finalites`, `defaults.bases_legales`, `defaults.duree_conservation_apres_fin_mission`, and `suggested_security_measures`. **Hold on to this dict** — it pre-fills steps 3–6.

## Step 2 — Identité du cabinet

Ask three questions in sequence:

1. "Nom du cabinet ou du responsable de traitement ?" → `controller.name`
2. "Adresse postale (numéro + rue + ville + code postal) ?" → `controller.address`
3. "Pays ?" (default `FR`) → `controller.country`

## Step 3 — Numéro d'inscription ordinale

Use the `ordinal_label` from Step 1's defaults dict. Ask: "Quel est votre {{ ordinal_label }} ?" If `ordinal_label` is empty (RH / generic), skip this step.

Capture as `controller.bar_or_order_number`.

## Step 4 — DPO

Surface the `dpo.required_hint` from defaults (e.g. for médecin: "obligatoire — données de santé Art. 9 traitées systématiquement").

Ask: "Avez-vous désigné un DPO ? (oui / non / inconnu)"

- **oui** → ask `dpo.name`, `dpo.email`, `dpo.phone` (the last two optional). Store under the `dpo` table.
- **non** → confirm with the user that the obligation hint doesn't apply to them. If they're unsure, recommend `oui` and pause the wizard.
- **inconnu** → write `dpo = { unknown = true }` and surface a manual_field hint in the resulting profile.

## Step 5 — Finalités

Display the `defaults.finalites` list (pre-filled from the profession). Ask: "Voici les finalités habituelles pour votre profession. Voulez-vous (a) les accepter telles quelles, (b) en éditer/retirer, (c) en ajouter ?"

Capture the final list as `defaults.finalites`.

Same pattern for `defaults.bases_legales` — show the defaults, let the user edit.

## Step 6 — Durée de conservation

Show `defaults.duree_conservation_apres_fin_mission` (pre-filled). Ask: "Voulez-vous garder cette durée par défaut ou la personnaliser ?"

Capture as `defaults.duree_conservation_apres_fin_mission`.

## Write the profile

Build the final profile dict:

```python
profile = {
    "controller": {
        "name": <step 2.1>,
        "profession": <step 1>,
        "address": <step 2.2>,
        "country": <step 2.3>,
        "bar_or_order_number": <step 3, if any>,
    },
    "dpo": <step 4 result>,
    "defaults": {
        "finalites": <step 5 finalites>,
        "bases_legales": <step 5 bases>,
        "duree_conservation_apres_fin_mission": <step 6>,
    },
}
```

Call:

```
mcp__piighost__controller_profile_set(profile=<profile>, scope="global")
```

Then call `mcp__piighost__controller_profile_get(scope="global")` to confirm the round-trip.

## Confirm

Print:

```
✅ Profil cabinet enregistré

Cabinet         : {{ controller.name }}
Profession      : {{ controller.profession }}
N° {{ ordinal_label }} : {{ controller.bar_or_order_number }}
DPO             : {{ dpo.name or "non désigné" }}
Finalités       : {{ defaults.finalites | length }}
Conservation    : {{ defaults.duree_conservation_apres_fin_mission }}

Vous pouvez maintenant utiliser :
  /hacienda:rgpd:registre   — Registre Art. 30
  /hacienda:rgpd:dpia       — Screening DPIA Art. 35
  /hacienda:rgpd:access     — Réponse Art. 15
  /hacienda:rgpd:forget     — Droit à l'oubli Art. 17

Pour ajuster un dossier spécifique :
  /hacienda:setup --project <nom-du-projet>
```

## --project mode

If the user invoked `/hacienda:setup --project <name>`:

1. Call `mcp__piighost__controller_profile_get(scope="project", project=<name>)` and show the merged view (global + any existing override).
2. Ask: "Quels champs voulez-vous surcharger pour ce dossier ?" — list the keys (controller / dpo / defaults).
3. For each chosen key, ask only that section's questions (using the same defaults pre-fill logic if profession changes).
4. Build a partial dict containing ONLY the overridden fields and call:

```
mcp__piighost__controller_profile_set(profile=<partial>, scope="project", project=<name>)
```

The daemon's deep-merge logic (existing in `ControllerProfileService`) preserves global values for unchanged fields.

## Refusals

- If `mcp__piighost__controller_profile_set` returns an error, surface it verbatim — do not retry silently. Likely cause: filesystem permissions on `~/.piighost/`.
- If the user picks `--project <name>` but the project doesn't exist, ask whether to (a) create it via `mcp__piighost__create_project`, or (b) cancel.
- The wizard MUST NOT call any non-controller-profile MCP tool. It writes one file and confirms; downstream skills do the actual compliance work.
```

- [ ] **Step 2: Bump plugin version**

Edit `.worktrees/hacienda-plugin/.claude-plugin/plugin.json` — change `"version": "0.6.0"` to `"version": "0.7.0"`.

- [ ] **Step 3: Verify the SKILL.md frontmatter is valid YAML**

```
PYTHONPATH=src .venv/Scripts/python.exe -c "
import re
content = open('.worktrees/hacienda-plugin/skills/setup/SKILL.md', encoding='utf-8').read()
m = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
assert m, 'no frontmatter'
import yaml
data = yaml.safe_load(m.group(1))
assert data['name'] == 'setup'
assert 'description' in data
print('frontmatter OK:', list(data.keys()))
"
```
(If `pyyaml` isn't in the venv, fall back to a manual eyeball — frontmatter must have valid `name:` and `description:` lines.)

- [ ] **Step 4: Commit in the plugin worktree**

```bash
git -C .worktrees/hacienda-plugin add skills/setup/SKILL.md .claude-plugin/plugin.json
git -C .worktrees/hacienda-plugin commit -m "feat(skills): /hacienda:setup wizard + v0.7.0

Onboarding wizard that walks the user through a 6-step conversational
setup of their RGPD controller profile, pre-filled with profession-
specific defaults from the bundled compliance/profiles/ TOMLs:

  1. profession (avocat / notaire / EC / médecin / RH / autre)
  2. cabinet identity (name, address, country)
  3. ordinal number (with profession-driven label)
  4. DPO (with profession-driven obligation hint)
  5. finalités (pre-filled, editable)
  6. durée de conservation (pre-filled, editable)

Bare /hacienda:setup writes the global profile. /hacienda:setup
--project <name> writes a per-project override.

Bumps plugin to v0.7.0."
```

DO NOT push yet — Task 7 handles push.

---

## Task 6: End-to-end smoke test for the wizard surface

**Files:**
- Create: `tests/integration/test_setup_wizard_e2e.py` (NEW — first integration test for the RGPD subsystem)

The wizard itself is a markdown skill (no Python to test directly), but its three MCP touchpoints must work end-to-end:
1. `controller_profile_defaults(profession="avocat")` returns the bundled dict.
2. `controller_profile_set(profile=<wizard-built>, scope="global")` writes the file.
3. `controller_profile_get(scope="global")` returns the round-tripped value.

This test simulates the full wizard flow at the service level (no daemon spin-up). It also closes followup #9 from Phase 2 ("End-to-end MCP integration test missing") at least for the wizard surface.

- [ ] **Step 1: Create the integration test directory if missing**

```bash
mkdir -p tests/integration
```

Add `tests/integration/__init__.py` (empty) if `tests/integration/` doesn't already exist.

- [ ] **Step 2: Write the test**

Create `tests/integration/test_setup_wizard_e2e.py`:

```python
"""End-to-end test simulating the /hacienda:setup wizard flow at the
service level (no daemon spin-up).

Mirrors the 6-step skill workflow: pick profession -> pre-fill via
defaults -> user-edits-on-top -> set -> get round-trip.
"""
from __future__ import annotations

import asyncio

import pytest

from piighost.service.config import ServiceConfig, RerankerSection
from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    cfg = ServiceConfig(reranker=RerankerSection(backend="none"))
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))


def test_wizard_avocat_global_flow(vault_dir, monkeypatch):
    """Simulate Step 1-6 of the wizard for an avocat, write global, read back."""
    svc = _svc(vault_dir, monkeypatch)

    # Step 1 — profession + load defaults
    defaults = asyncio.run(svc.controller_profile_defaults(profession="avocat"))
    assert defaults["controller"]["profession"] == "avocat"

    # Steps 2-6 — user fills in identity, accepts defaults
    profile = {
        "controller": {
            "name": "Cabinet Dupont & Associés",
            "profession": "avocat",
            "address": "12 rue de la Paix, 75002 Paris",
            "country": "FR",
            "bar_or_order_number": "Barreau de Paris #12345",
        },
        "dpo": {"name": "Marie Dupont", "email": "dpo@dupont-avocats.fr"},
        "defaults": {
            "finalites": defaults["defaults"]["finalites"],
            "bases_legales": defaults["defaults"]["bases_legales"],
            "duree_conservation_apres_fin_mission":
                defaults["defaults"]["duree_conservation_apres_fin_mission"],
        },
    }

    asyncio.run(svc.controller_profile_set(profile=profile, scope="global"))

    # Round-trip
    loaded = asyncio.run(svc.controller_profile_get(scope="global"))
    assert loaded["controller"]["name"] == "Cabinet Dupont & Associés"
    assert loaded["controller"]["bar_or_order_number"] == "Barreau de Paris #12345"
    assert loaded["dpo"]["email"] == "dpo@dupont-avocats.fr"
    assert "Conseil et représentation juridique" in loaded["defaults"]["finalites"]

    asyncio.run(svc.close())


def test_wizard_per_project_override_flow(vault_dir, monkeypatch):
    """Simulate /hacienda:setup --project flow: global stays, project override layers."""
    svc = _svc(vault_dir, monkeypatch)

    # Pre-existing global (set by a prior wizard run)
    global_profile = {
        "controller": {
            "name": "Cabinet Generic",
            "profession": "avocat",
            "country": "FR",
        },
        "defaults": {"finalites": ["Conseil juridique"]},
    }
    asyncio.run(svc.controller_profile_set(profile=global_profile, scope="global"))

    # Create the project the override targets
    asyncio.run(svc.create_project("dossier-acme"))

    # Per-project override — only the DPO field differs for this dossier
    override = {"dpo": {"name": "DPO Spécifique Acme", "email": "dpo@acme.fr"}}
    asyncio.run(svc.controller_profile_set(
        profile=override, scope="project", project="dossier-acme",
    ))

    # The merged read returns global + override
    merged = asyncio.run(svc.controller_profile_get(
        scope="project", project="dossier-acme",
    ))
    assert merged["controller"]["name"] == "Cabinet Generic"  # from global
    assert merged["dpo"]["email"] == "dpo@acme.fr"  # from override

    asyncio.run(svc.close())


def test_wizard_unknown_profession_falls_back(vault_dir, monkeypatch):
    """If the user picks 'autre', defaults() returns empty — wizard uses generic."""
    svc = _svc(vault_dir, monkeypatch)

    autre_defaults = asyncio.run(svc.controller_profile_defaults(profession="autre"))
    assert autre_defaults == {}

    generic_defaults = asyncio.run(svc.controller_profile_defaults(profession="generic"))
    assert generic_defaults["controller"]["profession"] == "generic"

    asyncio.run(svc.close())
```

- [ ] **Step 3: Run the tests**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/integration/test_setup_wizard_e2e.py -v --no-header
```
Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/__init__.py tests/integration/test_setup_wizard_e2e.py
git commit -m "test(integration): /hacienda:setup wizard end-to-end

Three integration tests covering the wizard's three MCP touchpoints:
  1. avocat global flow — defaults -> set -> get round-trip
  2. per-project override — global preserved, override layers
  3. unknown profession falls back to generic

First test under tests/integration/ — closes part of Phase 2 followup
#9 (end-to-end MCP coverage missing)."
```

---

## Task 7: Phase 4 final smoke test + push

**Files:**
- No new code — verification + push

- [ ] **Step 1: Run all Phase 4 tests together**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest \
  tests/unit/test_profile_loader.py \
  tests/unit/test_controller_profile_defaults_mcp.py \
  tests/integration/test_setup_wizard_e2e.py \
  -v --no-header
```
Expected: 5 + 4 + 3 = 12 passed.

- [ ] **Step 2: Run regression on Phase 0+1+2**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest \
  tests/unit/test_doc_authors_anonymisation.py \
  tests/unit/test_controller_profile.py \
  tests/unit/test_controller_profile_mcp.py \
  tests/unit/test_processing_register.py \
  tests/unit/test_dpia_screening.py \
  tests/unit/test_render_compliance_doc.py \
  tests/unit/test_no_pii_leak_phase2.py \
  tests/unit/test_no_pii_leak_phase1.py \
  tests/unit/test_subject_clustering.py \
  --no-header
```
Expected: all green (no Phase 4 regression on prior phases).

- [ ] **Step 3: Manual smoke (optional, requires Claude Desktop running)**

Restart the daemon, in a fresh Claude Desktop conversation:

```
/hacienda:setup
```

Walk through the 6 steps. Verify `~/.piighost/controller.toml` ends up with the values you typed. Then run `/hacienda:rgpd:registre` against an indexed project — confirm the new controller name appears in the rendered MD.

- [ ] **Step 4: Push piighost master**

```bash
ECC_SKIP_PREPUSH=1 git push jamon master
```

- [ ] **Step 5: Push the plugin worktree**

```bash
git -C .worktrees/hacienda-plugin push origin main
```

- [ ] **Step 6: Verify both pushes**

```bash
git -C . log --oneline jamon/master..HEAD     # should show nothing (in sync)
git -C .worktrees/hacienda-plugin log --oneline origin/main..HEAD   # should show nothing (in sync)
```

- [ ] **Step 7: (Optional) Phase 4 follow-ups doc**

If during the manual smoke you noticed UX rough edges or rough corners, capture them in `docs/superpowers/followups/2026-04-27-rgpd-phase4-followups.md` following the existing followups format. If no issues, skip.

---

## Self-review checklist

**Spec coverage (Wizard subset)**:

| Spec section | Implementing task |
|---|---|
| Bundled `compliance/profiles/` (Phase 0 spec, never landed) | Task 1 |
| `profile_loader` for the wizard | Task 2 |
| `controller_profile_defaults` service method | Task 3 |
| MCP wiring for `controller_profile_defaults` | Task 4 |
| 6-step conversational wizard skill | Task 5 |
| Per-project override mode (`--project <name>`) | Task 5 (`--project mode` section) |
| End-to-end test of the wizard surface | Task 6 |
| Smoke + push | Task 7 |

✓ Every Wizard spec item has a task. The `--project` mode is documented inside the same SKILL.md as the bare command — splitting it across two skills would be wrong (they share 100% of the prompt logic minus the load-existing-profile branch).

**Placeholder scan**: every code block has real code. No "TBD" / "implement later" / "similar to Task N". The 6 TOML files are written in full.

**Type consistency**:
- `controller_profile_defaults(profession: str) -> dict` — Task 3 def matches Task 4 dispatcher matches Task 5 skill workflow. ✓
- TOML schema `[controller] profession=...` matches what the wizard reads in Step 1 and what `controller_profile_set` accepts. ✓
- `bar_or_order_number` field name matches Phase 0's `ControllerInfo` Pydantic model. ✓
- The `dpo` table accepts `{name, email, phone}` OR `{unknown: true}` — both valid TOML, both deserialize through `ControllerProfileService`. ✓

**Scope check**: Phase 4 alone, single PR cycle, ~3–4 days. No new daemon spin-up, no new heavy deps, no new SQLite tables.

**Risk note**: the wizard relies on the model to drive the conversational flow correctly. If a model doesn't follow Step 4 (DPO obligation hint), the resulting profile may have `dpo = {}`. The downstream `processing_register` builder already treats missing DPO as "manual_field hint" so the failure mode is graceful — but worth flagging in Phase 4 follow-ups if observed in practice.

---

## Estimated effort

| Task | Effort |
|---|---|
| 1 — Bundled TOMLs | 1.5 h |
| 2 — profile_loader | 1 h |
| 3 — service method | 30 min |
| 4 — MCP wiring | 30 min |
| 5 — wizard skill | 2 h |
| 6 — integration test | 1 h |
| 7 — smoke + push | 30 min |
| **Total** | **~7 h (1 working day)** |

Compared to Phase 2 (~1.5 weeks for 9 tasks), Phase 4 is short — the heavy lifting (bundled templates, MCP boundary, ControllerProfileService) was done in Phases 0–2.
