"""Deterministically extend the Business Central mock fixtures with demo data.

The fixture-backed :class:`MockBusinessCentralClient` serves the Clientes /
Proyectos / Obligaciones / Dashboard views from committed JSON under
``app/integrations/business_central/fixtures/``. This script grows that demo
dataset with additional Faker-generated clients, one project each, and one
obligation instance per project, so those views show more than the original hand
authored rows.

Design constraints that keep the existing test suite green (see the tests under
``backend/tests/``):

* **Idempotent & deterministic.** Faker is seeded, and each run first strips any
  previously generated rows (keeping only the original id ranges
  ``cust-001..008`` / ``proj-001..012`` / ``pobl-001..012``) before regenerating
  the extension. Running it twice leaves the files byte-identical.
* **No collisions with exact-match assertions.** Generated names/NIFs are
  re-drawn until they contain none of the substrings the search/filter tests pin
  (``laboral`` / ``igi`` / ``puigcerdà``) and no existing NIF.
* **New projects avoid the pinned filter values** ``Iguala trimestral`` /
  ``Persona física`` so the projects filter ID-set tests stay valid.
* **New obligation instances are far-future** (unfiled), so the obligations
  service derives ``Al día`` for them and every existing Vencido/Próximo set and
  dashboard "próximas" assertion is untouched.

Run it from ``backend/``::

    python scripts/generate_bc_fixtures.py
"""

import json
from datetime import date, timedelta
from pathlib import Path

from faker import Faker

_FIXTURES_DIR = (
    Path(__file__).parent.parent
    / "app"
    / "integrations"
    / "business_central"
    / "fixtures"
)

# Highest original (hand-authored) numeric id per file; anything above is a
# previously generated extension row and is dropped before regenerating.
_ORIGINAL_MAX = {"customers": 8, "projects": 12, "project_obligations": 12}

# Substrings pinned by existing exact-match search/filter tests. Generated
# names/NIFs must contain none of them.
_NAME_DENYLIST = ("laboral", "igi", "puigcerdà")

# How many new clients to add (one project + one obligation instance each). Kept
# small enough that customers (8) and projects (12) stay under the 25-row default
# page size, so the "all on one page" tests remain single-page.
_NEW_CLIENTS = 6

_SEED = 2026

# Entity vocabularies reused from the original fixtures, deliberately excluding
# ``Persona física`` (pinned by test_entity_type_filter) and, for projects,
# ``Iguala trimestral`` (pinned by test_project_type_filter).
_CUSTOMER_TYPES = ("Societat", "Indivís", "Comunitat de béns", "Fundació")
_PROJECT_TYPES = ("Iguala mensual", "Iguala anual", "Altres")
_SERVICE_WORDS = (
    "Assessorament fiscal",
    "Gestió comptable",
    "Comptabilitat",
    "Fiscalitat integral",
)
# Existing catalog obligation ids to link the new instances to.
_OBLIGATION_IDS = (
    "obl-igi",
    "obl-irpf",
    "obl-is",
    "obl-ccaa",
    "obl-cass",
    "obl-informes",
)


def _load(name: str) -> list[dict]:
    return json.loads((_FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _id_num(row_id: str) -> int:
    """Numeric suffix of an id like ``cust-014`` -> ``14``."""
    return int(row_id.rsplit("-", 1)[1])


def _originals(rows: list[dict], name: str) -> list[dict]:
    """Keep only the hand-authored rows (drop any prior generated extension)."""
    ceiling = _ORIGINAL_MAX[name]
    return [r for r in rows if _id_num(r["id"]) <= ceiling]


def _has_denylisted(*values: str) -> bool:
    haystack = " ".join(values).casefold()
    return any(needle in haystack for needle in _NAME_DENYLIST)


def _dump_array(rows: list[dict]) -> str:
    """Serialize one object per line, matching the original fixtures' style."""
    lines = []
    for row in rows:
        fields = ", ".join(
            f'"{key}": {json.dumps(value, ensure_ascii=False)}'
            for key, value in row.items()
        )
        lines.append(f"  {{ {fields} }}")
    return "[\n" + ",\n".join(lines) + "\n]\n"


def generate() -> dict[str, list[dict]]:
    """Build the extended fixture arrays (originals + deterministic extension)."""
    fake = Faker()
    Faker.seed(_SEED)

    customers = _originals(_load("customers"), "customers")
    projects = _originals(_load("projects"), "projects")
    project_obligations = _originals(
        _load("project_obligations"), "project_obligations"
    )

    existing_nifs = {c["nif"].casefold() for c in customers}
    cust_start = _ORIGINAL_MAX["customers"] + 1
    proj_start = _ORIGINAL_MAX["projects"] + 1
    pobl_start = _ORIGINAL_MAX["project_obligations"] + 1

    for offset in range(_NEW_CLIENTS):
        # A clean client name + NIF, re-drawn until it collides with nothing.
        while True:
            name = fake.company()
            letter = fake.random_uppercase_letter()
            nif = f"{letter}{fake.random_int(100000, 999999)}"
            if _has_denylisted(name, nif) or nif.casefold() in existing_nifs:
                continue
            existing_nifs.add(nif.casefold())
            break

        while True:
            project_name = f"{_SERVICE_WORDS[offset % len(_SERVICE_WORDS)]} {fake.company()}"
            if not _has_denylisted(project_name):
                break

        cust_id = f"cust-{cust_start + offset:03d}"
        proj_id = f"proj-{proj_start + offset:03d}"
        pobl_id = f"pobl-{pobl_start + offset:03d}"
        customer_type = _CUSTOMER_TYPES[offset % len(_CUSTOMER_TYPES)]
        has_certificate = offset % 2 == 0

        customers.append(
            {
                "id": cust_id,
                "name": name,
                "nif": nif,
                "customer_type": customer_type,
                "responsible": fake.name(),
                "active_project_count": 1,
                "status": "Activo",
            }
        )
        projects.append(
            {
                "id": proj_id,
                "name": project_name,
                "customer_id": cust_id,
                "project_type": _PROJECT_TYPES[offset % len(_PROJECT_TYPES)],
                "entity_type": customer_type,
                "responsible": fake.name(),
                "technician": fake.name(),
                "has_certificate": has_certificate,
                "certificate_expiry": "2027-06-30" if has_certificate else None,
                "filing_date": None,
                "status": "Activo",
            }
        )
        # Far-future, unfiled -> derives "Al día"; disturbs no Vencido/Próximo set.
        due = date(2026, 11, 15) + timedelta(days=offset * 15)
        project_obligations.append(
            {
                "id": pobl_id,
                "project_id": proj_id,
                "obligation_id": _OBLIGATION_IDS[offset % len(_OBLIGATION_IDS)],
                "subject": True,
                "due_date": due.isoformat(),
                "submission_date": None,
                "status": "Pendiente",
            }
        )

    return {
        "customers": customers,
        "projects": projects,
        "project_obligations": project_obligations,
    }


def main() -> None:
    for name, rows in generate().items():
        path = _FIXTURES_DIR / f"{name}.json"
        path.write_text(_dump_array(rows), encoding="utf-8")
        print(f"Wrote {len(rows)} rows to {path.name}")


if __name__ == "__main__":
    main()
