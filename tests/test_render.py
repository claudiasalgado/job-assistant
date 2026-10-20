"""HTML del CV y límite de una página (decisión 021)."""

import pytest
from worker.render import render_html
from worker.tailor import build_tailored_cv


@pytest.fixture
def weasyprint():
    # WeasyPrint necesita pango: en macOS, DYLD_FALLBACK_LIBRARY_PATH (ver .env.example)
    try:
        import weasyprint
    except OSError:
        pytest.skip("WeasyPrint no encuentra pango en esta máquina")
    return weasyprint


@pytest.fixture
def cv(faithful_draft, profile):
    return build_tailored_cv(faithful_draft, profile)


@pytest.fixture
def long_cv(cv):
    """El mismo CV con los logros triplicados y alargados: no cabe en una página."""
    long = cv.model_copy(deep=True)
    for experience in long.experience:
        experience.achievements = [
            a.model_copy(update={"text": a.text + " relleno" * 60}) for a in experience.achievements
        ] * 3
    return long


def test_el_html_escapa_el_texto(cv):
    # autoescape: un "<" que venga de Gemini no puede inyectar HTML en el CV
    cv.summary = "<script>alert(1)</script>"

    html = render_html(cv)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_pdf_se_niega_a_dos_paginas(weasyprint, long_cv):
    from worker.render import CVTooLongError, render_pdf

    with pytest.raises(CVTooLongError):
        render_pdf(long_cv)


def test_fit_recorta_primero_la_experiencia_menos_relevante(weasyprint, long_cv):
    from worker.render import _layout, fit_to_one_page

    fitted = fit_to_one_page(long_cv)

    assert len(_layout(fitted).pages) == 1
    # La última experiencia (la menos relevante) se recorta antes, hasta un solo logro
    assert len(fitted.experience[-1].achievements) == 1
    assert all(len(e.achievements) >= 1 for e in fitted.experience)
    assert any("una página" in w for w in fitted.warnings)
    # El CV original no se toca
    assert len(long_cv.experience[-1].achievements) > 1


def test_si_no_cabe_ni_recortando_da_error(weasyprint, cv):
    from worker.render import CVTooLongError, fit_to_one_page

    for experience in cv.experience:
        experience.achievements = [experience.achievements[0].model_copy(update={"text": "relleno " * 900})]

    with pytest.raises(CVTooLongError):
        fit_to_one_page(cv)
