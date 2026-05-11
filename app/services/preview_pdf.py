"""Generate high-fidelity PDF previews for office documents."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from app.core.settings import settings

OFFICE_EXTENSIONS: tuple[str, ...] = (".doc", ".docx")


def get_preview_pdf_path(source_path: Path) -> Path:
    """Return a PDF path for previewing source_path.

    - `.pdf` returns itself.
    - `.doc` / `.docx` are converted to cached PDF files.
    """
    suffix = source_path.suffix.lower()
    if suffix == ".pdf":
        return source_path
    if suffix not in OFFICE_EXTENSIONS:
        raise ValueError(f"Unsupported preview conversion type: {suffix}")
    return _convert_office_to_pdf(source_path)


def _convert_office_to_pdf(source_path: Path) -> Path:
    settings.preview_pdf_dir.mkdir(parents=True, exist_ok=True)
    target_pdf = _cached_preview_target(source_path)
    if target_pdf.exists() and target_pdf.stat().st_size > 0:
        return target_pdf

    errors: list[str] = []
    converted = _try_convert_with_libreoffice(source_path, target_pdf, errors)
    if not converted:
        converted = _try_convert_with_word_com(source_path, target_pdf, errors)

    if not converted:
        joined = " | ".join(errors) if errors else "unknown conversion failure"
        raise RuntimeError(f"Could not convert file to PDF preview: {joined}")
    return target_pdf


def _cached_preview_target(source_path: Path) -> Path:
    resolved = source_path.resolve()
    stat = resolved.stat()
    key = f"{resolved}|{stat.st_size}|{stat.st_mtime_ns}"
    digest = hashlib.sha1(key.encode("utf-8", errors="ignore")).hexdigest()
    return settings.preview_pdf_dir / f"{digest}.pdf"


def _try_convert_with_libreoffice(source_path: Path, target_pdf: Path, errors: list[str]) -> bool:
    bins = _candidate_soffice_bins()
    if not bins:
        errors.append("LibreOffice binary not found")
        return False

    for soffice_bin in bins:
        try:
            with tempfile.TemporaryDirectory(prefix="office_preview_", dir=str(settings.preview_pdf_dir)) as temp_dir:
                temp_out_dir = Path(temp_dir)
                command = [
                    soffice_bin,
                    "--headless",
                    "--invisible",
                    "--nologo",
                    "--norestore",
                    "--nodefault",
                    "--nofirststartwizard",
                    "--convert-to",
                    "pdf:writer_pdf_Export",
                    "--outdir",
                    str(temp_out_dir),
                    str(source_path),
                ]
                proc = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=max(15, settings.preview_convert_timeout_sec),
                    check=False,
                )
                if proc.returncode != 0:
                    stderr = (proc.stderr or "").strip()
                    stdout = (proc.stdout or "").strip()
                    errors.append(f"LibreOffice failed ({Path(soffice_bin).name}): {stderr or stdout or 'exit!=0'}")
                    continue

                converted = temp_out_dir / f"{source_path.stem}.pdf"
                if not converted.exists() or converted.stat().st_size <= 0:
                    errors.append(f"LibreOffice produced empty output ({Path(soffice_bin).name})")
                    continue

                _atomic_replace_file(converted, target_pdf)
                return True
        except Exception as exc:
            errors.append(f"LibreOffice exception ({Path(soffice_bin).name}): {exc}")
            continue

    return False


def _try_convert_with_word_com(source_path: Path, target_pdf: Path, errors: list[str]) -> bool:
    if os.name != "nt":
        errors.append("Word COM conversion only available on Windows")
        return False

    source = str(source_path.resolve())
    temp_target = str(target_pdf.with_suffix(".tmp.pdf"))
    target = str(target_pdf.resolve())

    for temp in (target_pdf.with_suffix(".tmp.pdf"), target_pdf):
        if temp.exists():
            temp.unlink(missing_ok=True)

    script = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            f"$source = '{_ps_escape_single_quote(source)}'",
            f"$target = '{_ps_escape_single_quote(temp_target)}'",
            "$word = $null",
            "$doc = $null",
            "try {",
            "  $word = New-Object -ComObject Word.Application",
            "  $word.Visible = $false",
            "  $word.DisplayAlerts = 0",
            "  $doc = $word.Documents.Open($source, $false, $true)",
            "  $doc.ExportAsFixedFormat($target, 17)",
            "} finally {",
            "  if ($doc -ne $null) { $doc.Close([ref]$false) }",
            "  if ($word -ne $null) { $word.Quit() }",
            "}",
        ]
    )

    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        script,
    ]

    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=max(20, settings.preview_convert_timeout_sec),
            check=False,
        )
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            stdout = (proc.stdout or "").strip()
            errors.append(f"Word COM failed: {stderr or stdout or 'exit!=0'}")
            return False

        temp_pdf = Path(temp_target)
        if not temp_pdf.exists() or temp_pdf.stat().st_size <= 0:
            errors.append("Word COM produced empty output")
            return False

        _atomic_replace_file(temp_pdf, Path(target))
        return True
    except Exception as exc:
        errors.append(f"Word COM exception: {exc}")
        return False


def _candidate_soffice_bins() -> list[str]:
    seen: set[str] = set()
    candidates: list[str] = []

    def push(value: str | None) -> None:
        if not value:
            return
        key = value.strip().strip('"')
        if not key or key in seen:
            return
        seen.add(key)
        candidates.append(key)

    push(settings.soffice_bin)
    push(shutil.which("soffice"))
    push(shutil.which("soffice.com"))
    push(shutil.which("libreoffice"))

    if os.name == "nt":
        windows_bins = (
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files\LibreOffice\program\soffice.com",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.com",
        )
        for path_value in windows_bins:
            if Path(path_value).exists():
                push(path_value)

    return candidates


def _atomic_replace_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    source.replace(target)


def _ps_escape_single_quote(value: str) -> str:
    return value.replace("'", "''")
