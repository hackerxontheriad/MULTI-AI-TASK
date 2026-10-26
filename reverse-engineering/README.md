# Safe reverse-engineering / static inspection lane

This folder documents a defensive, non-executing workflow for code/ZIP/APK coursework and your own applications: inventory archives, inspect manifests and permissions, enumerate endpoints, review dependencies, find accidental secret-like strings, and record findings. The scanner never runs code found inside an uploaded archive.

```bash
python scripts/audit_project.py /path/to/project-or-archive.zip --json reports/audit.json
```

The scanner flags suspicious patterns for manual review; a match is not proof of vulnerability, and no static scanner can certify an application secure. Use this only on assets you own or are authorized to assess. It does not provide payment bypass, credential theft, stealth, or exploit automation.
