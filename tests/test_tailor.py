"""Validación del CV que propone Gemini: lo que no es verificable no llega al PDF."""

import json

from core.models import DraftAchievement, DraftExperience
from worker.tailor import PROFILE_FIELDS_NOT_SENT, build_tailored_cv, tailor_cv


def test_borrador_fiel_pasa_sin_avisos(faithful_draft, profile):
    cv = build_tailored_cv(faithful_draft, profile)

    assert cv.warnings == []
    assert [e.id for e in cv.experience] == [e.id for e in profile.experience]


def test_experiencia_inventada_se_descarta(faithful_draft, profile):
    faithful_draft.experiences.append(DraftExperience(experience_id="inventada", achievements=[]))

    cv = build_tailored_cv(faithful_draft, profile)

    assert "inventada" not in [e.id for e in cv.experience]
    assert any("inventada" in w for w in cv.warnings)


def test_logro_de_otra_experiencia_se_descarta(faithful_draft, profile):
    # Un logro real, pero colgado de la experiencia que no es la suya (decisión 007)
    other = profile.experience[1].achievements[0]
    faithful_draft.experiences[0].achievements.append(DraftAchievement(source_id=other.id, text=other.text))

    cv = build_tailored_cv(faithful_draft, profile)

    assert other.id not in [a.source_id for a in cv.experience[0].achievements]


def test_logro_con_cifras_cambiadas_vuelve_al_original(faithful_draft, profile):
    # Decisión 013: se pierde la adaptación, nunca el logro ni la veracidad
    original = profile.experience[0].achievements[0]
    faithful_draft.experiences[0].achievements[0] = DraftAchievement(
        source_id=original.id, text="Pipeline que redujo de 5 horas a 1 minuto la carga."
    )

    cv = build_tailored_cv(faithful_draft, profile)

    assert cv.experience[0].achievements[0].text == original.text
    assert any(original.id in w for w in cv.warnings)


def test_logro_que_pierde_una_cifra_vuelve_al_original(faithful_draft, profile):
    original = profile.experience[0].achievements[0]
    faithful_draft.experiences[0].achievements[0] = DraftAchievement(
        source_id=original.id, text="Pipeline de ingesta diaria en Python."
    )

    cv = build_tailored_cv(faithful_draft, profile)

    assert cv.experience[0].achievements[0].text == original.text


def test_skills_sin_distinguir_mayusculas_y_con_el_nombre_del_perfil(faithful_draft, profile):
    faithful_draft.skills = ["python", "KUBERNETES"]

    cv = build_tailored_cv(faithful_draft, profile)

    assert [s.name for s in cv.skills] == ["Python"]
    assert any("kubernetes" in w for w in cv.warnings)


def test_experiencia_omitida_da_aviso(faithful_draft, profile):
    # Decisión 009: se avisa, no se añade
    faithful_draft.experiences.pop()

    cv = build_tailored_cv(faithful_draft, profile)

    assert any(profile.experience[-1].id in w for w in cv.warnings)


def test_resumen_que_menciona_un_nivel_da_aviso(faithful_draft, profile):
    faithful_draft.summary = "Ingeniera de datos sénior con experiencia en Python."

    cv = build_tailored_cv(faithful_draft, profile)

    assert any("senior" in w for w in cv.warnings)


def test_a_gemini_nunca_le_llegan_los_datos_personales(offer, profile, faithful_draft, monkeypatch):
    # Pendiente desde la decisión 014: comprobar que la lista negra se aplica
    monkeypatch.setenv("GEMINI_MODEL", "modelo-de-prueba")
    sent = {}

    class FakeModels:
        def generate_content(self, model, contents, config):
            sent.update(json.loads(contents))
            return type("Response", (), {"text": faithful_draft.model_dump_json()})()

    client = type("Client", (), {"models": FakeModels()})()
    tailor_cv(offer, profile, client=client)

    assert PROFILE_FIELDS_NOT_SENT <= {"personal", "seniority"}
    for field in PROFILE_FIELDS_NOT_SENT:
        assert field not in sent["profile"]
    assert profile.personal.email not in json.dumps(sent)
