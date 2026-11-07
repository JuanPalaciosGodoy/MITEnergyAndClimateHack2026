"""Verify active source/reference URLs and files in one saved lookup response.

Run from the repository root: uv run python scripts/check_links.py
Reports live failures rather than treating blocked sites as working links.
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import requests

# Running a file directly puts scripts/, rather than the repository, on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from API import checklist_table


def check_url(url):
    result = {"url": url, "checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "status": "FAIL", "http_status": None, "final_url": None, "detail": None}
    try:
        with requests.get(url, stream=True, timeout=(10, 30)) as response:
            result.update(http_status=response.status_code, final_url=response.url)
            response.raise_for_status()
            if 'json' in response.headers.get('Content-Type', ''):
                payload = response.json()
                if isinstance(payload, dict) and payload.get('error'):
                    raise ValueError(str(payload['error']))
            result['status'] = 'PASS'
    except (requests.RequestException, ValueError) as error:
        result['detail'] = str(error)[:400]
    return result


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else 'data/processed/site_checklist/site.json')
    site = json.loads(path.read_text())
    table = checklist_table(site)
    urls = set(table['data_source'].drop_nulls().to_list())
    urls.update(s.get('query_url') or s['source_url'] for s in site['sources'].values())
    urls.update(r['registry_website'] for r in site.get('sources',{}).get('land_records',{}).get('records',[]) if r.get('registry_website'))
    for reference in site.get("references",{}).values():
        if reference.get('url'):
            urls.add(reference['url'])
        urls.update(reference.get('additional_urls', []))
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(check_url, sorted(u for u in urls if isinstance(u,str) and u.startswith(('http://','https://')))))
    report = pl.from_dicts(results, infer_schema_length=None)
    output = Path('data/processed/link_checks.csv')
    output.parent.mkdir(parents=True, exist_ok=True)
    report.write_csv(output)
    local_files = set(table['local_file'].drop_nulls().to_list())
    missing = [f for f in local_files if not Path(f).is_file()]
    print(report.select('status', 'http_status', 'url', 'detail'))
    print(f'{report.height} unique remote links checked; {len(local_files)} local files checked. Report: {output}')
    if missing:
        print('Missing local files:', missing)
    return 1 if missing or report.filter(pl.col('status') != 'PASS').height else 0


if __name__ == '__main__':
    raise SystemExit(main())
