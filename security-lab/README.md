# MADX Local Kali Lab

This is a disposable local container for authorized security testing and static triage. It is separate from the Render web service; the public site does not expose an interactive Kali shell.

Build and open a shell from the repository root:

```bash
docker compose -f security-lab/compose.yaml build
docker compose -f security-lab/compose.yaml run --rm kali-lab
```

Only files in `security-lab/work/` are mounted writable. The container has a read-only root filesystem, drops Linux capabilities except `NET_RAW` for basic packet-based checks, enables `no-new-privileges`, has no privileged mode, and does not mount the Docker socket or host root. These constraints reduce risk but do not make untrusted malware safe to run; do not execute unknown binaries inside or outside the container.

Use `nmap` only against targets you own or have written authorization to assess. Do not run broad scans against public IP ranges. Example for your own lab host: `nmap -sT -sV 192.168.1.10` after checking that the address belongs to your lab.

Tools include `file`, `strings`, `binwalk`, `yara`, `ripgrep`, `jq`, `unzip`, `binutils`, `python3`, and `nmap`. `read_only: true` and `cap_drop: ALL` mean some advanced packet or exploit workflows will not work by design.


This lab is local-only and is not attached to the public MADX terminal endpoint. Do not scan systems without explicit authorization.
