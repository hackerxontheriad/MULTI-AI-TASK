#!/usr/bin/env python3
"""Non-executing inventory and static-risk scan for a project folder or ZIP/APK archive."""
from __future__ import annotations
import argparse, hashlib, json, re, zipfile
from pathlib import Path
from typing import Iterable

MAX_FILE = 2 * 1024 * 1024
TEXT_EXTS = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".htm", ".css", ".json", ".xml", ".yml", ".yaml", ".toml", ".ini", ".env", ".gradle", ".java", ".kt", ".php", ".sh", ".bat", ".ps1", ".sql", ".md", ".txt", ".properties"}
PATTERNS = [
    ("possible_secret", re.compile(r"(?i)(api[_-]?key|access[_-]?token|client[_-]?secret|password|secret)\s*[:=]\s*['\"][^'\"]{8,}['\"]")),
    ("dynamic_code_execution", re.compile(r"\b(eval|exec)\s*\(")),
    ("shell_execution_review", re.compile(r"subprocess\.(?:Popen|run|call)\s*\(")),
    ("js_dynamic_execution", re.compile(r"\bnew\s+Function\s*\(|\beval\s*\(")),
    ("insecure_cleartext_network", re.compile(r"(?i)usesCleartextTraffic\s*=\s*\"true\"|http://(?!127\.0\.0\.1|localhost)")),
    ("unsafe_html_insertion", re.compile(r"\.innerHTML\s*=")),
]

def is_text(name: str) -> bool:
    path = Path(name)
    return path.suffix.lower() in TEXT_EXTS or path.name in {"Dockerfile", "Procfile", "Makefile", ".gitignore", ".dockerignore"}

def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("target", help="project directory or ZIP/APK/AAB archive")
    ap.add_argument("--json", dest="json_out", help="write JSON report to a path")
    ap.add_argument("--max-files", type=int, default=5000)
    args=ap.parse_args(); target=Path(args.target)
    if not target.exists(): ap.error("target does not exist")
    findings=[]; files=[]; endpoints=set(); deps=set(); permissions=set(); total_bytes=0
    def inspect(name: str, data: bytes, size: int):
        nonlocal total_bytes
        total_bytes += size
        files.append({"path":name,"bytes":size,"sha256":hashlib.sha256(data).hexdigest()})
        if not is_text(name) or len(data)>MAX_FILE: return
        try: text=data.decode("utf-8",errors="replace")
        except Exception: return
        for line_no,line in enumerate(text.splitlines(),1):
            for label,pat in PATTERNS:
                if pat.search(line):
                    snippet=line.strip()
                    # Never print the suspected secret value in the report.
                    if label=="possible_secret": snippet=pat.sub(lambda m: m.group(1)+"=<REDACTED>",snippet)
                    findings.append({"type":label,"path":name,"line":line_no,"snippet":snippet[:220]})
        endpoints.update(re.findall(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+",text))
        if Path(name).name.lower() in {"requirements.txt","requirements-dev.txt","requirements-integrations.txt","package.json","pom.xml","build.gradle","build.gradle.kts"}:
            for line in text.splitlines():
                clean=line.strip()
                if clean and not clean.startswith(("#","//","*","{") ) and len(deps)<1000: deps.add(f"{name}: {clean[:180]}")
        if "AndroidManifest.xml" in name:
            permissions.update(re.findall(r"android:name=['\"]([^'\"]*permission[^'\"]*)['\"]",text,re.I))
    if target.is_dir():
        candidates=sorted(p for p in target.rglob("*") if p.is_file() and not any(x in {".git","node_modules",".venv","__pycache__"} for x in p.parts))
        for file in candidates[:args.max_files]:
            try: inspect(file.relative_to(target).as_posix(),file.read_bytes(),file.stat().st_size)
            except OSError: pass
    elif zipfile.is_zipfile(target):
        with zipfile.ZipFile(target) as z:
            candidates=[i for i in z.infolist() if not i.is_dir() and not i.filename.startswith("__MACOSX/")]
            for info in candidates[:args.max_files]:
                try:
                    if info.file_size>MAX_FILE and is_text(info.filename):
                        inspect(info.filename,b"",info.file_size)
                    else: inspect(info.filename,z.read(info.filename),info.file_size)
                except (OSError,KeyError,zipfile.BadZipFile): findings.append({"type":"archive_read_error","path":info.filename})
    else:
        findings.append({"type":"unsupported_binary_or_single_file","path":target.name,"note":"Use a directory, ZIP, APK, or AAB (ZIP-format) input."})
    report={"target":str(target),"files_scanned":len(files),"total_uncompressed_bytes":total_bytes,"files":files,"possible_findings":findings,"endpoint_urls":sorted(endpoints),"dependency_lines":sorted(deps),"android_permission_names":sorted(permissions),"warning":"Heuristic static scan only. No contained code was executed; review every finding manually."}
    rendered=json.dumps(report,indent=2,ensure_ascii=False)
    if args.json_out: Path(args.json_out).write_text(rendered+"\n",encoding="utf-8")
    print(f"Scanned {len(files)} files ({total_bytes} uncompressed bytes). Findings: {len(findings)}. URLs: {len(endpoints)}. Dependency entries: {len(deps)}.")
    for item in findings[:120]: print(f"[{item.get('type')}] {item.get('path')}:{item.get('line','?')} {item.get('snippet',item.get('note',''))}")
    if len(findings)>120: print(f"… {len(findings)-120} more findings are in JSON output.")
    if args.json_out: print(f"JSON report: {args.json_out}")
    return 0
if __name__=='__main__': raise SystemExit(main())
