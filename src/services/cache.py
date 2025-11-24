
import os, json, time
from pathlib import Path
from typing import Dict, Any, List

BASE = Path('data/cache')
BASE.mkdir(parents=True, exist_ok=True)

def company_dir(company: str) -> Path:
    safe = ''.join(c for c in company if c.isalnum() or c in ('-', '_')).lower()
    d = BASE / safe
    d.mkdir(parents=True, exist_ok=True)
    return d

def write_json(company: str, name: str, data: Dict[str, Any]):
    d = company_dir(company)
    with open(d / f'{name}.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def read_json(company: str, name: str) -> Dict[str, Any]:
    d = company_dir(company)
    p = d / f'{name}.json'
    if p.exists():
        return json.load(open(p, encoding='utf-8'))
    return {}

def path_for(company: str, filename: str) -> Path:
    d = company_dir(company)
    return d / filename

# ---------- TTL helpers ----------

def _latest_mtime(path: Path) -> float:
    if not path.exists(): return 0.0
    latest = 0.0
    for root, _, files in os.walk(path):
        for f in files:
            fp = Path(root) / f
            try:
                m = fp.stat().st_mtime
                if m > latest: latest = m
            except Exception:
                continue
    return latest

def is_cache_stale(company: str, ttl_days: int) -> bool:
    """Return True if the company's cache is older than ttl_days."""
    d = company_dir(company)
    latest = _latest_mtime(d)
    if latest == 0.0: return True
    age_sec = time.time() - latest
    return age_sec > (ttl_days * 86400)

def prune_company_cache(company: str, ttl_days: int) -> None:
    """Delete files older than ttl_days for the given company (PDF/JSON/PNG)."""
    d = company_dir(company)
    cutoff = time.time() - (ttl_days * 86400)
    for root, _, files in os.walk(d):
        for f in files:
            fp = Path(root) / f
            try:
                if fp.stat().st_mtime < cutoff:
                    if fp.suffix.lower() in ('.pdf', '.json', '.png'):
                        fp.unlink(missing_ok=True)
            except Exception:
                continue

def list_cached_downloads(company: str) -> List[Dict[str, str]]:
    """Return cached PDFs from deep_collect.json (if any and present)."""
    deep = read_json(company, "deep_collect")
    downloaded = deep.get("downloaded", [])
    present = []
    for d in downloaded:
        p = Path(d.get("path", ""))
        u = d.get("url")
        if p.exists() and u:
            present.append({"path": str(p), "url": u})
    return present
