from agentops.agent.skills import SKILLS, format_skill_for_prompt, select_skill


def test_all_skills_have_the_required_fields():
    assert len(SKILLS) >= 5
    for skill in SKILLS:
        assert skill.name
        assert skill.instructions
        assert skill.keywords


def test_selects_debugging_skill():
    skill = select_skill("Der er en bug i beregningen — testen fejler med et crash.")
    assert skill is not None
    assert skill.name == "debugging"


def test_selects_security_review_skill():
    skill = select_skill("Lav en security review af auth-modulet for sårbarheder.")
    assert skill is not None
    assert skill.name == "security_review"


def test_selects_test_generation_skill():
    skill = select_skill("Skriv nye tests for at forbedre testcoverage af parseren.")
    assert skill is not None
    assert skill.name == "test_generation"


def test_selects_database_migration_review_skill():
    skill = select_skill("Gennemgå denne Alembic migration og databaseskemaændringen.")
    assert skill is not None
    assert skill.name == "database_migration_review"


def test_selects_api_review_skill():
    skill = select_skill("Review dette REST API endpoint i FastAPI-routeren.")
    assert skill is not None
    assert skill.name == "api_review"


def test_returns_none_when_nothing_matches():
    skill = select_skill("Forklar hvad dette repository generelt handler om.")
    assert skill is None


def test_format_skill_for_prompt_includes_instructions_and_rules():
    skill = select_skill("Der er en bug, testen fejler.")
    assert skill is not None
    text = format_skill_for_prompt(skill)
    assert skill.instructions in text
    assert "Sikkerhedsregler" in text
