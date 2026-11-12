SUPABASE_DOC_PREFIX = "storage:"
SUPABASE_DOC_BUCKET = "applications"
SUPABASE_DOC_MIME = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def download_supabase_doc(value, supabase_cfg=None, timeout=60):
    """C1/C2/J3 values that start with "storage:" are files in the private Supabase bucket.
    Same contract as download_drive_file: returns (bytes, mime), or (None, None) on any failure,
    so the caller flags it for manual review instead of crashing the step."""
    try:
        path = value[len(SUPABASE_DOC_PREFIX):].strip()
        if not path or path.startswith("/") or ".." in path.split("/"):
            raise ValueError("unsafe storage path: %r" % path[:80])
        if supabase_cfg is None:
            cfg_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "intake_sheets_config.json")
            with open(cfg_file, encoding="utf-8") as f:
                supabase_cfg = (json.load(f).get("ingest") or {}).get("supabase", {})
        url = (supabase_cfg.get("url") or "").rstrip("/")
        key = load_supabase_key(supabase_cfg)
        if not url or not key:
            raise ValueError("supabase url or key not configured")
        req = urllib.request.Request(
            "%s/storage/v1/object/authenticated/%s/%s" % (url, SUPABASE_DOC_BUCKET, urllib.parse.quote(path)),
            headers={"apikey": key, "Authorization": "Bearer " + key})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(11 * 1024 * 1024 + 1)
        if len(data) > 11 * 1024 * 1024:
            raise ValueError("document larger than the 10 MB bucket limit")
        return data, SUPABASE_DOC_MIME.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
    except Exception as e:
        print("  ⚠️  supabase document download failed: %s: %s" % (type(e).__name__, e))
        return None, None
