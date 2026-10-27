"""Validated project-manifest parsing and ZIP packaging. Never executes generated files."""
from __future__ import annotations
import io, json, re, zipfile
from pathlib import PurePosixPath
from typing import Any

MAX_FILES = 30
MAX_FILE_BYTES = 350_000
MAX_TOTAL_BYTES = 4_000_000
BLOCKED_NAMES = {".env", ".env.local", ".env.production", ".env.development", "id_rsa", "id_ed25519", "authorized_keys", "credentials.json", "service-account.json", "secrets.json", "token.json"}

class ProjectOutputError(ValueError):
    pass


def parse_json_object(text: str) -> dict[str, Any]:
    raw = text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise ProjectOutputError("Selected model did not return a valid JSON object.")
        try:
            data = json.loads(raw[start:end + 1])
        except json.JSONDecodeError as exc:
            raise ProjectOutputError("Selected model returned malformed JSON; no ZIP was created.") from exc
    if not isinstance(data, dict):
        raise ProjectOutputError("The model output must be a JSON object.")
    return data


def safe_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 220:
        raise ProjectOutputError("Each file needs a short relative path.")
    name = value.replace("\\", "/").strip()
    # Permit harmless ./ prefixes from model output, but never normalize away ../.
    while name.startswith("./"):
        name = name[2:]
    path = PurePosixPath(name)
    if (not name or name.startswith("/") or path.is_absolute()
            or any(part in {"", ".", ".."} for part in name.split("/"))
            or any(part in {".", ".."} for part in path.parts)):
        raise ProjectOutputError(f"Unsafe project path rejected: {value[:100]}")
    if any(ord(c) < 32 for c in name) or ":" in path.parts[0]:
        raise ProjectOutputError("Control characters and drive-prefixed paths are not allowed.")
    basename = path.name.lower()
    if basename in BLOCKED_NAMES or basename.endswith((".pem", ".p12", ".key")):
        raise ProjectOutputError(f"Credential-like file name rejected: {basename}")
    if any(part.lower() in {"node_modules", ".git", ".ssh", ".aws", ".azure", ".kube", "__pycache__", ".venv"} for part in path.parts):
        raise ProjectOutputError("Build output may not include dependency caches, VCS internals, or credential directories.")
    return path.as_posix()


def normalize_files(value: Any) -> dict[str, bytes]:
    if not isinstance(value, list) or not value:
        raise ProjectOutputError("Model output must include a non-empty files array.")
    if len(value) > MAX_FILES:
        raise ProjectOutputError(f"The project exceeds the limit of {MAX_FILES} files. Split the request into smaller builds.")
    files: dict[str, bytes] = {}
    total = 0
    for item in value:
        if not isinstance(item, dict):
            raise ProjectOutputError("Each file entry must be an object with path and content.")
        path = safe_relative_path(item.get("path", ""))
        content = item.get("content")
        if not isinstance(content, str):
            raise ProjectOutputError(f"File {path} has no text content.")
        blob = content.encode("utf-8")
        if len(blob) > MAX_FILE_BYTES:
            raise ProjectOutputError(f"File {path} exceeds the {MAX_FILE_BYTES}-byte per-file limit.")
        total += len(blob)
        if total > MAX_TOTAL_BYTES:
            raise ProjectOutputError(f"Project exceeds the {MAX_TOTAL_BYTES}-byte source limit.")
        if path in files:
            raise ProjectOutputError(f"Duplicate output path: {path}")
        files[path] = blob
    return files


def make_zip(files: dict[str, bytes], project_name: str, readme: str = "") -> bytes:
    if not files:
        raise ProjectOutputError("No safe files to package.")
    clean_name = re.sub(r"[^A-Za-z0-9._-]+", "-", project_name.strip())[:70].strip("-.") or "madx-project"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path, blob in sorted(files.items()):
            normalized = safe_relative_path(path)
            info = zipfile.ZipInfo(f"{clean_name}/{normalized}")
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, blob)
        if readme.strip() and not any(name.lower().endswith("readme.md") for name in files):
            archive.writestr(f"{clean_name}/README.md", readme[:20000].encode("utf-8"))
    return out.getvalue()
