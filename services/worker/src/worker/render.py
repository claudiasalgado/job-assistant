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


def render_pdf(cv: TailoredCV, output: Path) -> Path:
    """Genera el PDF con WeasyPrint, etiquetado como PDF/UA-1 para que lo lea bien un ATS."""
    # Import aquí y no arriba: WeasyPrint carga librerías del sistema (pango) al importarse,
    # y así render_html funciona y se puede testear aunque no estén instaladas.
    from weasyprint import HTML

    # base_url: desde dónde se resuelven styles.css y las fuentes
    HTML(string=render_html(cv), base_url=str(TEMPLATES_DIR)).write_pdf(
        output, pdf_variant="pdf/ua-1"
    )
    return output
