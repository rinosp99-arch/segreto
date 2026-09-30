"""Download all public content of LATO SEGRETO: creators, categories, articles, settings and every image/video.

    python herunterladen.py

Result next to this script:
  daten/*.json        raw API answers (models incl. secret side, categories, articles, settings)
  medien/...          every media file, same path as on the old site
  medien-liste.json   old URL -> local file
Safe to run again: existing files are skipped.
"""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://secret-side.emergent.host"
HERE = Path(__file__).parent
DATA = HERE / "daten"
MEDIA = HERE / "medien"
UA = "Mozilla/5.0 (lato-segreto-neubau)"
MEDIA_EXT = re.compile(r"\.(jpe?g|png|webp|gif|avif|svg|mp4|webm|mov|m4v|mp3|m4a|ogg)(\?|$)", re.I)


def get_json(path):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def save(name, obj):
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_urls(obj, found):
    if isinstance(obj, dict):
        for v in obj.values():
            collect_urls(v, found)
    elif isinstance(obj, list):
        for v in obj:
            collect_urls(v, found)
    elif isinstance(obj, str):
        s = obj.strip()
        if s.startswith("/api/uploads/") or (s.startswith("http") and MEDIA_EXT.search(s)):
            found.add(s)


def local_path(url):
    if url.startswith("/api/uploads/"):
        rel = urllib.parse.unquote(url[len("/api/uploads/"):].split("?")[0])
    else:
        p = urllib.parse.urlparse(url)
        rel = "extern/" + p.netloc + urllib.parse.unquote(p.path)
    return MEDIA / rel


def download(url, target):
    full = BASE + url if url.startswith("/") else url
    full = urllib.parse.quote(full, safe=":/?&=%")
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(full, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".part")
            tmp.write_bytes(data)
            tmp.replace(target)
            return len(data)
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                raise
            time.sleep(2 * attempt)
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 * attempt)


def main():
    found = set()

    models = get_json("/api/models?limit=500")["items"]
    print(f"{len(models)} Creatorinnen")
    full_models = []
    for m in models:
        slug = m["slug"]
        detail = get_json(f"/api/models/{urllib.parse.quote(slug)}")
        try:
            secret = get_json(f"/api/models/{urllib.parse.quote(slug)}/segreto")
        except urllib.error.HTTPError:
            secret = {}
        full_models.append({"pubblico": detail, "segreto": secret})
        print(f"  {slug}")
    save("modelle.json", full_models)

    cats = get_json("/api/categories")["items"]
    save("kategorien.json", cats)
    arts = get_json("/api/articles?limit=500")["items"]
    full_arts = [get_json(f"/api/articles/{urllib.parse.quote(a['slug'])}") for a in arts]
    save("artikel.json", full_arts)
    settings = get_json("/api/settings")
    save("einstellungen.json", settings)
    try:
        pellicola = get_json("/api/pellicola")
        save("pellicola.json", pellicola)
    except urllib.error.HTTPError:
        pellicola = {}
    print(f"{len(cats)} Kategorien, {len(full_arts)} Artikel\n")

    for obj in (full_models, cats, full_arts, settings, pellicola):
        collect_urls(obj, found)

    urls = sorted(found)
    print(f"{len(urls)} Mediendateien gefunden, lade ...")
    mapping, missing, new_bytes, skipped = {}, [], 0, 0
    for i, url in enumerate(urls, 1):
        target = local_path(url)
        mapping[url] = str(target.relative_to(HERE)).replace("\\", "/")
        if target.exists() and target.stat().st_size > 0:
            skipped += 1
        else:
            try:
                new_bytes += download(url, target)
            except Exception as e:
                missing.append(f"{url}\t{e}")
        if i % 25 == 0 or i == len(urls):
            print(f"  {i}/{len(urls)}  ({new_bytes / 1e6:.0f} MB neu, {skipped} schon da, {len(missing)} fehlen)")

    (HERE / "medien-liste.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    if missing:
        (HERE / "fehlende-medien.txt").write_text("\n".join(missing), encoding="utf-8")
    print(f"\nFertig: {len(urls) - len(missing)} von {len(urls)} Dateien da, {len(missing)} fehlen.")


if __name__ == "__main__":
    main()
