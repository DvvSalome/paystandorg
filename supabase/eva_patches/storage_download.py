"""Patch for Eva's intake_pipeline.py: download a document that lives in Supabase Storage.

The view intake_rows gives C1, C2 and J3 as "storage:<path>" (for example
"storage:APP-2027-0001/C1-registro.pdf"). Today the pipeline only downloads Google Drive
links, so it marks those values as not downloadable and cannot check name and address
against the registration document.

How to use it (Iván adapts names to the real code; standard library only):
    from storage_download import is_supabase_document, download_supabase_document
    if is_supabase_document(c1_val):
        ing = config["ingest"]["supabase"]
        local_path = download_supabase_document(c1_val, ing["url"], load_supabase_key(ing), run_dir)
        # then run the same 3-tier text extraction the Drive branch uses, on local_path
"""
import pathlib, re, urllib.parse, urllib.request

STORAGE_PREFIX = "storage:"
BUCKET = "applications"
MAX_BYTES = 11 * 1024 * 1024          # the bucket already caps uploads at 10 MB


def is_supabase_document(value):
    return isinstance(value, str) and value.startswith(STORAGE_PREFIX)


def download_supabase_document(value, supabase_url, key, dest_dir, timeout=60):
    """Returns the local path of the downloaded file. Raises ValueError on a bad path."""
    path = value[len(STORAGE_PREFIX):].strip()
    if not path or path.startswith("/") or ".." in path.split("/"):
        raise ValueError(f"unsafe storage path: {path[:80]!r}")
    url = (f"{supabase_url.rstrip('/')}/storage/v1/object/authenticated/{BUCKET}/"
           + urllib.parse.quote(path))
    req = urllib.request.Request(url, headers={"apikey": key, "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("document larger than the bucket limit")
    dest = pathlib.Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / re.sub(r"[^\w.\-]+", "_", path.replace("/", "__"))[:150]
    out.write_bytes(data)
    return str(out)
