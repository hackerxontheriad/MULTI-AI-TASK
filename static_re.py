"""Non-executing static archive review for owned/authorized ZIP, APK and AAB files."""
from __future__ import annotations
import hashlib, re, zipfile
from pathlib import PurePosixPath
from typing import Any

MAX_ENTRIES = 2500
MAX_UNCOMPRESSED = 40 * 1024 * 1024
MAX_TEXT_BYTES = 1_000_000
TEXT_EXTS = {".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".html", ".css", ".json", ".xml", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".php", ".java", ".kt", ".kts", ".go", ".rs", ".sh", ".bash", ".sql", ".properties", ".gradle", ".txt", ".md", ".env.example"}
PATTERNS = [
    ("possible_secret", re.compile(r"(?i)(api[_-]?key|access[_-]?token|client[_-]?secret|password|private[_-]?key)\s*[:=]\s*['\"]?[^\s'\"]{8,}")),
    ("dynamic_execution_review", re.compile(r"\b(eval|exec)\s*\(")),
    ("shell_execution_review", re.compile(r"\bsubprocess\.(run|Popen|call)\s*\(")),
    ("unsafe_html_review", re.compile(r"\.innerHTML\s*=")),
    ("disabled_tls_review", re.compile(r"(?i)(verify\s*=\s*False|rejectUnauthorized\s*:\s*false)")),
]

def _text_findings(name: str, text: str) -> list[dict[str, Any]]:
    found = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for label, pattern in PATTERNS:
            match = pattern.search(line)
            if match:
                snippet = line.strip()[:180]
                if label == "possible_secret":
                    snippet = pattern.sub("credential-like-value=<REDACTED>", snippet)
                found.append({"type": label, "path": name[:220], "line": lineno, "snippet": snippet})
    return found

def audit_archive(path: str) -> dict[str, Any]:
    files, findings, endpoints, deps, permissions, total = [], [], set(), set(), set(), 0
    if not zipfile.is_zipfile(path):
        raise ValueError("This file is not a readable ZIP/APK/AAB/JAR archive.")
    with zipfile.ZipFile(path) as archive:
        entries = [x for x in archive.infolist() if not x.is_dir() and not x.filename.startswith("__MACOSX/")]
        if len(entries) > MAX_ENTRIES:
            raise ValueError(f"Archive contains more than {MAX_ENTRIES} files; scan refused to limit resource use.")
        for item in entries:
            name = item.filename.replace("\\", "/")
            parts = PurePosixPath(name).parts
            if PurePosixPath(name).is_absolute() or ".." in parts or (parts and ":" in parts[0]):
                findings.append({"type": "unsafe_archive_path", "path": name[:220], "note": "Path traversal-like path; file was not extracted."})
            total += max(0, item.file_size)
            if total > MAX_UNCOMPRESSED:
                raise ValueError(f"Archive expands past {MAX_UNCOMPRESSED} bytes; scan refused to limit resource use.")
            files.append({"path": name[:220], "compressed_bytes": item.compress_size, "bytes": item.file_size})
            suffix = PurePosixPath(name).suffix.lower()
            if suffix not in TEXT_EXTS and PurePosixPath(name).name.lower() not in {"dockerfile", "procfile", "makefile", "androidmanifest.xml"}:
                continue
            if item.file_size > MAX_TEXT_BYTES:
                findings.append({"type": "large_text_file_skipped", "path": name[:220], "bytes": item.file_size})
                continue
            try:
                raw = archive.read(item)
                text = raw.decode("utf-8", errors="replace")
            except Exception:
                findings.append({"type": "archive_read_error", "path": name[:220]})
                continue
            findings.extend(_text_findings(name, text))
            endpoints.update(re.findall(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", text))
            if PurePosixPath(name).name.lower() in {"requirements.txt", "requirements-lite.txt", "requirements-dev.txt", "package.json", "pom.xml", "build.gradle", "build.gradle.kts"}:
                for line in text.splitlines():
                    line = line.strip()
                    if line and len(deps) < 500 and not line.startswith(("#", "//", "*")):
                        deps.add(f"{name}: {line[:160]}")
            if "androidmanifest.xml" in name.lower():
                permissions.update(re.findall(r"android:name=['\"]([^'\"]*permission[^'\"]*)['\"]", text, re.I))
    return {"archive_files": len(files), "uncompressed_bytes": total, "files": files[:500],
            "finding_count": len(findings), "findings": findings[:250], "endpoint_urls": sorted(endpoints)[:500],
            "dependency_lines": sorted(deps)[:500], "android_permissions": sorted(permissions),
            "warning": "Static heuristics only. No files were extracted or executed. A finding needs manual review and is not proof of a vulnerability."}
