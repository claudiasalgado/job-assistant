"""Puntuación del matching: Gemini empareja, el código valida y puntúa (decisión 023)."""

from core.models import SkillCoverage, SkillMatchDraft
from worker.matcher import build_skill_match


def draft(must, nice=()):
    return SkillMatchDraft(
        must_have=[SkillCoverage(offer_skill=o, profile_skill=p) for o, p in must],
        nice_to_have=[SkillCoverage(offer_skill=o, profile_skill=p) for o, p in nice],
    )


def test_todo_cubierto_da_100(offer, profile):
    d = draft(
        [("Python", "Python"), ("SQL", "SQL"), ("Git", "Git")],
        [("GCP", "Google Cloud Platform"), ("Pytest", "Python")],
    )

    match = build_skill_match(d, offer, profile)

    assert match.score == 100
    assert match.gaps == []


def test_peso_80_obligatorias_20_deseables(offer, profile):
    # 2 de 3 obligatorias y 1 de 2 deseables: 0,8 · 2/3 + 0,2 · 1/2 = 0,633
    d = draft([("Python", "Python"), ("SQL", "SQL"), ("Git", None)], [("GCP", "Google Cloud Platform"), ("Pytest", None)])

    match = build_skill_match(d, offer, profile)

    assert match.score == 63
    assert match.gaps == ["Git"]
    assert match.missing_nice_to_have == ["Pytest"]


def test_nombre_que_no_esta_en_el_perfil_no_cuenta(offer, profile):
    d = draft([("Python", "Python"), ("SQL", "SQL avanzado"), ("Git", "Git")])

    match = build_skill_match(d, offer, profile)

    assert "SQL" in match.gaps


def test_skill_que_gemini_se_salta_cuenta_como_no_cubierta(offer, profile):
    d = draft([("Python", "Python")])

    match = build_skill_match(d, offer, profile)

    assert match.gaps == ["SQL", "Git"]


def test_sin_deseables_las_obligatorias_pesan_el_100(offer, profile):
    offer = offer.model_copy(update={"nice_to_have": []})
    d = draft([("Python", "Python"), ("SQL", None), ("Git", None)])

    assert build_skill_match(d, offer, profile).score == 33


def test_sin_distinguir_mayusculas(offer, profile):
    d = draft([("python", "PYTHON"), ("SQL", "sql"), ("Git", "git")])

    assert build_skill_match(d, offer, profile).gaps == []
