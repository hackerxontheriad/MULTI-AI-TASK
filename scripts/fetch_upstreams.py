#!/usr/bin/env python3
"""Opt-in shallow fetch of the user-requested repositories; never executes fetched code."""
from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path

REPOS={
 "BetterChatGPT":"https://github.com/ztjhz/BetterChatGPT.git",
 "freegpt-webui":"https://github.com/ramon-victor/freegpt-webui.git",
 "Buddo":"https://github.com/ArthurKNielsen/Buddo.git",
 "youcoded":"https://github.com/itsdestin/youcoded.git",
 "freemicro":"https://github.com/eliBenven/freemicro.git",
 "OmniSearches":"https://github.com/KiwiGaze/OmniSearches.git",
 "Free-GPT4-WEB-API":"https://github.com/aledipa/Free-GPT4-WEB-API.git",
 "OmniRoute":"https://github.com/cheaper-inference/OmniRoute.git",
 "New-API":"https://github.com/QuantumNous/new-api.git",
 "One-API":"https://github.com/songquanpeng/one-api.git",
}
def main():
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--repo',choices=sorted(REPOS),action='append',help='repo to fetch; can be repeated')
 ap.add_argument('--all-requested',action='store_true',help='fetch all listed repos (some are large)')
 ap.add_argument('--destination',default='external/upstreams',help='destination directory')
 ap.add_argument('--yes',action='store_true',help='confirm network cloning')
 args=ap.parse_args()
 if not args.yes: ap.error('this does network access; pass --yes only after reviewing each repository and its license')
 names=args.repo or (sorted(REPOS) if args.all_requested else [])
 if not names: ap.error('select --repo NAME or --all-requested')
 dest=Path(args.destination); dest.mkdir(parents=True,exist_ok=True)
 rc=0
 for name in names:
  path=dest/name
  if path.exists(): print(f'SKIP {name}: destination already exists ({path})'); continue
  print(f'FETCH {name} -> {path}')
  result=subprocess.run(['git','clone','--depth','1',REPOS[name],str(path)],check=False)
  if result.returncode: print(f'FAILED {name}: git exit {result.returncode}',file=sys.stderr); rc=1
  else: print(f'OK {name}: fetched only; no package install or code execution performed')
 print('Next: inspect each LICENSE, dependency manifest, release/security notes, and runtime isolation before integration.')
 return rc
if __name__=='__main__': raise SystemExit(main())
