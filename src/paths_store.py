"""Pastas de entrada/saída partilhadas entre UI e CLI (ficheiro local ignorado pelo git)."""
from __future__ import annotations

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "itranslatebooks_config.json"

DEFAULT_BOOKS_IN = "books_IN"
DEFAULT_BOOKS_OUT = "books_OUT"


def _to_stored_path(user_value: str, default: str) -> str:
    s = (user_value or "").strip() or default
    p = Path(s)
    if not p.is_absolute():
        return str(p).replace("\\", "/")
    try:
        rel = p.resolve().relative_to(PROJECT_ROOT.resolve())
        return str(rel).replace("\\", "/")
    except ValueError:
        return str(p.resolve())


def load_app_settings() -> dict:
    if not CONFIG_PATH.is_file():
        return {
            "books_in_dir": DEFAULT_BOOKS_IN,
            "books_out_dir": DEFAULT_BOOKS_OUT,
            "glossary": "",
            "use_context": True,
            "save_translation_report": False,
        }
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {
            "books_in_dir": DEFAULT_BOOKS_IN,
            "books_out_dir": DEFAULT_BOOKS_OUT,
            "glossary": "",
            "use_context": True,
            "save_translation_report": False,
        }
    inn = str(data.get("books_in_dir") or "").strip() or DEFAULT_BOOKS_IN
    out = str(data.get("books_out_dir") or "").strip() or DEFAULT_BOOKS_OUT
    gloss = str(data.get("glossary", ""))
    use_ctx = data.get("use_context", True)
    save_report = bool(data.get("save_translation_report", False))
    return {
        "books_in_dir": inn,
        "books_out_dir": out,
        "glossary": gloss,
        "use_context": use_ctx,
        "save_translation_report": save_report,
    }


def save_app_settings(
    books_in_dir: str,
    books_out_dir: str,
    glossary: str = "",
    use_context: bool = True,
    save_translation_report: bool = False,
) -> None:
    payload = {
        "books_in_dir": _to_stored_path(books_in_dir, DEFAULT_BOOKS_IN),
        "books_out_dir": _to_stored_path(books_out_dir, DEFAULT_BOOKS_OUT),
        "glossary": glossary,
        "use_context": use_context,
        "save_translation_report": save_translation_report,
    }
    CONFIG_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def resolve_books_dirs() -> tuple[str, str]:
    s = load_app_settings()
    rin = s["books_in_dir"]
    rout = s["books_out_dir"]
    in_abs = rin if os.path.isabs(rin) else os.path.join(str(PROJECT_ROOT), rin)
    out_abs = rout if os.path.isabs(rout) else os.path.join(str(PROJECT_ROOT), rout)
    return os.path.normpath(in_abs), os.path.normpath(out_abs)


def ensure_books_dirs() -> tuple[str, str]:
    in_abs, out_abs = resolve_books_dirs()
    os.makedirs(in_abs, exist_ok=True)
    os.makedirs(out_abs, exist_ok=True)
    return in_abs, out_abs


def output_path_for_epub(input_epub_path: str, books_out_abs: str) -> str:
    name = os.path.basename(input_epub_path)
    return os.path.join(books_out_abs, name.replace(".epub", "_PT_BR.epub"))
