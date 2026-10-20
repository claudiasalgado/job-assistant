from pathlib import Path

from core.models import Skill, TailoredCV
from jinja2 import Environment, FileSystemLoader, StrictUndefined

TEMPLATES_DIR = Path(__file__).parent / "templates"

# Los únicos textos del CV que no salen del perfil
LABELS = {
    "es": {
        "experience": "Experiencia",
        "education": "Formación académica",
        "projects": "Proyectos",
        "skills": "Competencias técnicas",
        "certifications": "Certificaciones",
        "languages": "Idiomas",
        "volunteering": "Voluntariado",
        "present": "Actualidad",
    },
    "en": {
        "experience": "Experience",
        "education": "Education",
        "projects": "Projects",
        "skills": "Technical Skills",
        "certifications": "Certifications",
        "languages": "Languages",
        "volunteering": "Volunteering",
        "present": "Present",
    },
}

# Cómo se muestra cada clave de personal.links; las que no estén aquí, capitalizadas
LINK_LABELS = {"linkedin": "LinkedIn", "github": "GitHub"}

# autoescape: un texto con "<" o "&" se muestra tal cual en vez de romper el HTML.
# StrictUndefined: una variable mal escrita en la plantilla falla en vez de salir vacía.
_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True, undefined=StrictUndefined
)
_env.filters["month"] = lambda value: "/".join(reversed(value.split("-")))  # 2025-02 -> 02/2025


def _skill_groups(skills: list[Skill]) -> list[tuple[str | None, list[str]]]:
    """Agrupa por categoría en el orden en que aparecen, que es el de relevancia."""
    groups: dict[str | None, list[str]] = {}
    for skill in skills:
        groups.setdefault(skill.category, []).append(skill.name)
    return list(groups.items())


def render_html(cv: TailoredCV) -> str:
    if cv.language not in LABELS:
        raise ValueError(
            f"No hay textos de plantilla para el idioma {cv.language!r} "
            f"(disponibles: {', '.join(LABELS)})"
        )

    personal = cv.personal
    contact = [x for x in (personal.location, personal.phone, personal.email) if x]
    links = [(LINK_LABELS.get(k, k.capitalize()), url) for k, url in personal.links.items()]

    return _env.get_template("cv.html").render(
        cv=cv,
        t=LABELS[cv.language],
        contact=contact,
        links=links,
        skill_groups=_skill_groups(cv.skills),
    )


MAX_PAGES = 1
PDF_VARIANT = "pdf/ua-1"


class CVTooLongError(ValueError):
    """El CV no cabe en MAX_PAGES ni quitando todos los logros que se pueden quitar."""


def _layout(cv: TailoredCV):
    """Maqueta el CV sin escribir el PDF: el resultado sabe cuántas páginas ocupa."""
    # Import aquí y no arriba: WeasyPrint carga librerías del sistema (pango) al importarse,
    # y así render_html funciona y se puede testear aunque no estén instaladas.
    from weasyprint import HTML

    # base_url: desde dónde se resuelven styles.css y las fuentes
    return HTML(string=render_html(cv), base_url=str(TEMPLATES_DIR)).render(pdf_variant=PDF_VARIANT)


def fit_to_one_page(cv: TailoredCV) -> TailoredCV:
    """Devuelve una copia del CV que cabe en una página (decisión 021).

    Mientras ocupe más, quita el último logro de la última experiencia que
    tenga más de uno: el orden es el de relevancia que dio Gemini, así que se
    va siempre lo que menos importa para la oferta. Ninguna experiencia se
    queda sin logros (decisión 009). Cada recorte queda en warnings.
    """
    # Copia profunda: quien llama conserva su CV intacto
    cv = cv.model_copy(deep=True)
    while len(_layout(cv).pages) > MAX_PAGES:
        experience = next((e for e in reversed(cv.experience) if len(e.achievements) > 1), None)
        if experience is None:
            raise CVTooLongError(
                f"El CV ocupa más de {MAX_PAGES} página incluso con un solo logro por "
                "experiencia: hay que acortar el perfil"
            )
        removed = experience.achievements.pop()
        cv.warnings.append(
            f"Logro {removed.source_id} quitado para que el CV quepa en una página"
        )
    return cv


def render_pdf(cv: TailoredCV, output: Path | None = None) -> bytes:
    """Genera el PDF con WeasyPrint, etiquetado como PDF/UA-1 para que lo lea bien un ATS.

    Nunca genera más de MAX_PAGES páginas: si el CV no cabe, lanza
    CVTooLongError. Para recortarlo antes, fit_to_one_page.

    Devuelve los bytes del PDF. Si se pasa output, además lo escribe en disco
    (lo usa el CLI; la api los sube a Cloud Storage sin pasar por disco).
    """
    document = _layout(cv)
    # La garantía está aquí y no en quien llama: ningún camino escribe un PDF más largo
    if len(document.pages) > MAX_PAGES:
        raise CVTooLongError(
            f"El CV ocupa {len(document.pages)} páginas; usa fit_to_one_page antes de render_pdf"
        )

    # Sin destino, write_pdf devuelve los bytes en vez de escribir un fichero
    pdf = document.write_pdf(pdf_variant=PDF_VARIANT)
    if output:
        output.write_bytes(pdf)
    return pdf
