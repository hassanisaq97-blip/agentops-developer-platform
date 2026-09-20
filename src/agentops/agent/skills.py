"""Modulært skills-system.

En `Skill` er ren, statisk data — instruktioner, anbefalede MCP-tools,
sikkerhedsregler og tjek — IKKE kode. Agenten får ALDRIG alle skills i sin
prompt fra start: `select_skill()` er en billig, deterministisk
keyword-klassificering, der kører FØR noget LLM-kald, og kun den ene mest
relevante skills instruktioner bliver tilføjet til system-prompten (se
`agentops.agent.orchestrator`). At tilføje en ny skill kræver kun en ny
`Skill(...)`-post i `SKILLS` nedenfor — ingen ændringer andre steder.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Skill(BaseModel):
    name: str
    description: str
    keywords: list[str]
    instructions: str
    recommended_tools: list[str] = Field(default_factory=list)
    security_rules: list[str] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)


DEBUGGING = Skill(
    name="debugging",
    description="Find og ret en konkret fejl/bug i koden.",
    keywords=["fejl", "bug", "fejler", "crash", "exception", "stacktrace", "debug", "nedbrud"],
    instructions=(
        "Find rodårsagen til fejlen, før du foreslår en rettelse. Reproducér fejlen "
        "(kør den relevante testsuite), isolér den fejlende linje, og lav den mindste "
        "rettelse, der løser den underliggende årsag — undgå at ændre urelateret kode."
    ),
    recommended_tools=[
        "get_repository_status",
        "run_tests",
        "search_code",
        "read_file",
        "get_git_diff",
        "apply_patch",
    ],
    security_rules=[
        "Ret aldrig en fejlende test ved at slette eller udkommentere den — ret den "
        "underliggende kode."
    ],
    checks=["Kør testsuiten igen efter rettelsen for at bekræfte, at fejlen er væk."],
)

SECURITY_REVIEW = Skill(
    name="security_review",
    description="Undersøg kode for sikkerhedsproblemer, uden at ændre den.",
    keywords=[
        "sikkerhed",
        "security",
        "sårbarhed",
        "vulnerability",
        "cve",
        "injection",
        "secrets",
        "review",
    ],
    instructions=(
        "Gennemgå de relevante filer for kendte sårbarhedsmønstre: command injection, "
        "path traversal, hardkodede secrets, usikker deserialisering, manglende "
        "input-validering. Rapportér konkrete fund med filsti — foreslå ikke rettelser, "
        "medmindre du eksplicit bliver bedt om det."
    ),
    recommended_tools=["search_code", "read_file", "get_git_diff", "get_repository_status"],
    security_rules=["Udfør aldrig en mistænkt sårbar kodesti for at 'bevise' den virker."],
    checks=[
        "Er der hardkodede API-nøgler/adgangskoder?",
        "Er der shell=True eller lignende command injection-mønstre?",
        "Er filsti-input valideret mod path traversal?",
    ],
)

TEST_GENERATION = Skill(
    name="test_generation",
    description="Skriv nye tests for eksisterende eller ny kode.",
    keywords=["test", "tests", "testcoverage", "unittest", "pytest", "testdækning"],
    instructions=(
        "Identificér utestet adfærd i den relevante kode, og skriv målrettede tests, "
        "der dækker både den forventede sti og mindst ét edge case. Kør testsuiten "
        "bagefter for at bekræfte, at de nye tests består."
    ),
    recommended_tools=["search_code", "read_file", "run_tests", "apply_patch"],
    checks=["Kør testsuiten efter de nye tests er tilføjet, og bekræft at de består."],
)

DATABASE_MIGRATION_REVIEW = Skill(
    name="database_migration_review",
    description="Gennemgå database-skema-ændringer/migrations.",
    keywords=["migration", "database", "skema", "schema", "alembic", "sql", "kolonne", "tabel"],
    instructions=(
        "Gennemgå migrations for reversibilitet (fungerer downgrade?), for destruktive "
        "ændringer uden en sikker strategi, og bekræft at op-/downgrade rent faktisk er "
        "testet mod den faktiske databasemotor, ikke kun antaget."
    ),
    recommended_tools=["search_code", "read_file", "get_git_diff", "run_tests"],
    security_rules=["Foreslå aldrig at droppe en kolonne/tabel uden en eksplicit advarsel."],
    checks=[
        "Findes der en fungerende downgrade-sti?",
        "Er migrationen testet mod den rigtige databasemotor (ikke kun SQLite)?",
    ],
)

API_REVIEW = Skill(
    name="api_review",
    description="Gennemgå eller design et API-endpoint.",
    keywords=["api", "endpoint", "rest", "http", "route", "fastapi"],
    instructions=(
        "Tjek input-validering, fejlhåndtering og at responsen matcher den dokumenterede "
        "kontrakt. Se efter manglende eller forkerte HTTP-statuskoder."
    ),
    recommended_tools=["search_code", "read_file", "get_project_documentation"],
    checks=[
        "Er alt input valideret?",
        "Returneres korrekte HTTP-statuskoder ved fejl?",
    ],
)

SKILLS: list[Skill] = [
    DEBUGGING,
    SECURITY_REVIEW,
    TEST_GENERATION,
    DATABASE_MIGRATION_REVIEW,
    API_REVIEW,
]


def select_skill(task_description: str) -> Skill | None:
    """Deterministisk keyword-matching — INGEN LLM-kald. Pointen er netop at undgå
    at bruge en dyr model-forespørgsel blot til at vælge, hvilke instruktioner der
    er relevante, før den egentlige agent-kørsel starter."""
    text = task_description.lower()
    best: tuple[int, Skill] | None = None
    for skill in SKILLS:
        score = sum(1 for keyword in skill.keywords if keyword.lower() in text)
        if score > 0 and (best is None or score > best[0]):
            best = (score, skill)
    return best[1] if best else None


def format_skill_for_prompt(skill: Skill) -> str:
    lines = [f"--- Aktiveret skill: {skill.name} ({skill.description}) ---", skill.instructions]
    if skill.security_rules:
        lines.append("Sikkerhedsregler: " + " ".join(skill.security_rules))
    if skill.checks:
        lines.append("Tjek inden du afslutter: " + " ".join(skill.checks))
    return "\n".join(lines)
