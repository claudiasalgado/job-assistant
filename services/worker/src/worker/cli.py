"""Genera un CV adaptado a una oferta desde la terminal (sprint 1, todo en local).

Uso:
    uv run --package worker --env-file .env cv OFERTA.txt [--lang es] [--profiles DIR] [--out DIR]
"""

import argparse
import re
import sys
import unicodedata
from pathlib import Path

from core.models import Profile

from worker.extractor import extract_offer
from worker.render import fit_to_one_page, render_pdf
from worker.tailor import tailor_cv


def _slug(text: str) -> str:
    """"Nubelia Analytics, S.L." -> "nubelia-analytics-s-l", para usarlo en un nombre de fichero."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


def _profile_path(profiles_dir: Path, language: str) -> Path:
    path = profiles_dir / f"profile.{language}.json"
    if not path.exists():
        available = sorted(p.name for p in profiles_dir.glob("profile.*.json"))
        sys.exit(
            f"No hay perfil en '{language}' ({path}). "
            f"Elige otro idioma con --lang. Disponibles: {', '.join(available) or 'ninguno'}"
        )
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera un CV adaptado a una oferta.")
    parser.add_argument("offer", type=Path, help="fichero de texto con la oferta")
    parser.add_argument(
        "--lang", help="idioma del CV (es, en...). Por defecto, el idioma de la oferta"
    )
    parser.add_argument(
        "--profiles", type=Path, default=Path("data/private"),
        help="carpeta con los profile.{idioma}.json (por defecto, data/private)",
    )
    parser.add_argument(
        "--out", type=Path, default=Path("data/private/output"),
        help="carpeta donde se guarda el PDF (por defecto, data/private/output)",
    )
    args = parser.parse_args()

    if not args.offer.exists():
        sys.exit(f"No encuentro la oferta: {args.offer}")

    # Si el idioma ya se conoce, se comprueba antes de llamar a Gemini: un error gratis
    if args.lang:
        _profile_path(args.profiles, args.lang)

    print(f"Extrayendo la oferta {args.offer}...")
    offer = extract_offer(args.offer.read_text(encoding="utf-8"))
    language = args.lang or offer.language
    profile_path = _profile_path(args.profiles, language)
    profile = Profile.model_validate_json(profile_path.read_text(encoding="utf-8"))

    print(f"Adaptando el CV ({language}) a {offer.title} en {offer.company or 'empresa sin nombre'}...")
    cv = fit_to_one_page(tailor_cv(offer, profile))

    args.out.mkdir(parents=True, exist_ok=True)
    output = args.out / f"cv_{_slug(offer.company or 'oferta')}_{language}.pdf"
    render_pdf(cv, output)
    print(f"\nPDF generado: {output}")

    if cv.warnings:
        print(f"\nRevisa estos {len(cv.warnings)} avisos antes de enviarlo:")
        for warning in cv.warnings:
            print(f"  - {warning}")
    else:
        print("\nSin avisos de la validación. Aun así, léelo antes de enviarlo.")


if __name__ == "__main__":
    main()
