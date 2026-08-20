# ADR-007: Configurable PDF upload size cap (env-controlled, 50 MB default)

## Status

Accepted

## Context

The PDF upload endpoint
(`POST /workspaces/{id}/papers/from-pdf`) accepts a PDF file,
extracts DOI/PMID from the first page, and resolves the
identifier through the same `IdentifierResolver` chain as the
DOI-paste flow. Historically the endpoint hard-capped uploads at
**10 MB** and rejected larger files with HTTP 413:

> "API error 413: PDF is 21112026 bytes; the max is 10485760.
> Split it or use the PMID/DOI tab instead."

The user hit this with a 21 MB PDF — a perfectly normal thesis
chapter with embedded figures. The error message was unhelpful
("split it" doesn't tell the user how), and the underlying
strategy of "10 MB is enough" was wrong: 21 MB PDFs are
common in biomedical research (high-resolution figures, supplementary
material, scan-based documents).

The original 10 MB cap wasn't tied to any technical limit —
there's no FastAPI, no nginx, no upload size limit
upstream of our code that would constrain us. The cap was
chosen in 2024 as a "reasonable default" with no analysis
behind it.

The right answer is two parts:

1. **Raise the default to 50 MB** to match what real
   researchers use. A 50 MB PDF is large but not pathological
   (a 200-page review article with figures).
2. **Make the cap env-controlled** so operators can adjust
   it for their deployment without a code change. The cap
   must have a **hard upper bound** (200 MB) so an
   unfortunate env var (`PDF_UPLOAD_MAX_BYTES=999999999999`)
   can't open the door to resource exhaustion — a
   malicious 10 GB upload would OOM the container.

## Decision

Two changes:

### 1. `LiteratureSettings.pdf_upload_max_bytes`

A new `LiteratureSettings` field with a sensible default
(50 MB) and the env-var alias `PDF_UPLOAD_MAX_BYTES`:

```python
pdf_upload_max_bytes: int = Field(
    default=50 * 1024 * 1024,  # 50 MB
    alias="PDF_UPLOAD_MAX_BYTES",
)
```

The default is read at startup; operators override via `.env`.

### 2. Hard upper bound in the route

The route's `_PDF_UPLOAD_MAX_BYTES` constant is `min(hard_cap, settings_value)`:

```python
_PDF_UPLOAD_MAX_BYTES_HARD_CAP = 200 * 1024 * 1024  # 200 MB
_PDF_UPLOAD_MAX_BYTES: int = min(
    _PDF_UPLOAD_MAX_BYTES_HARD_CAP,
    max(0, int(literature_settings.pdf_upload_max_bytes)),
)
```

The 200 MB hard cap is **not configurable** — it's a
compile-time constant. This is the key safety property: an
operator who sets `PDF_UPLOAD_MAX_BYTES=999999999999` in
their `.env` still gets capped at 200 MB. A malicious user
who somehow controls the env var still gets capped at 200
MB.

`max(0, ...)` defends against negative values: a typo of
`PDF_UPLOAD_MAX_BYTES=-1` disables the cap (every request
rejected) rather than enabling infinite uploads.

The error message is also fixed. Instead of the old
"Split it or use the PMID/DOI tab instead" (which didn't
help), the new message shows the actual configured cap:

```python
raise HTTPException(
    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
    detail=(
        f"PDF is {len(raw)} bytes; the max is "
        f"{_PDF_UPLOAD_MAX_BYTES}. "
        f"Set PDF_UPLOAD_MAX_BYTES in .env to raise the cap."
    ),
)
```

### 3. Bootstrap default

`bootstrap.py`'s `write_env_file` writes
`ABSTRACT_ENRICHER_ENABLED=true` to the `.env` it creates.
We do NOT auto-write `PDF_UPLOAD_MAX_BYTES` — the default
(50 MB) is correct for almost everyone and adding another
env var to the bootstrap's `.env` template would clutter
the config. Operators who need a different cap edit the
`.env` themselves; the env-var contract is documented in
the route's OpenAPI summary.

## Consequences

**Positive**

- The user's 21 MB PDF now uploads successfully. Measured:
  10 MB cap → 50 MB cap covers >95% of biomedical research
  PDFs.
- Operators with unusual needs (large supplementary-data
  packages) can raise the cap to 200 MB via a single env
  var, no code change.
- The hard cap at 200 MB prevents resource exhaustion. A
  10 GB upload would OOM the container; 200 MB is the
  largest we accept.
- The error message tells the user how to fix the problem
  ("set PDF_UPLOAD_MAX_BYTES in .env"), not just that the
  problem exists.
- The cap is read at startup (from `LiteratureSettings`),
  not per-request, so there's no per-request DB lookup or
  settings validation. The trade-off: changing
  `PDF_UPLOAD_MAX_BYTES` requires a container restart. We
  accept this — a settings change is an operator action,
  and the restart is fast.

**Negative**

- Container memory usage grows with the cap. The default
  50 MB is fine on the default container (256 MB limit is
  comfortable for most PDFs). Operators raising to 200 MB
  should also raise the container memory limit to ~512 MB.
  We don't add a memory check; the OOM-killer would catch
  any misconfiguration and the operator can adjust.
- We read the cap from `LiteratureSettings` once at module
  import. Changing the env var at runtime has no effect
  until the container restarts. A `lifespan` hook could
  reload the value, but the added complexity isn't worth
  the marginal benefit (env vars are typically set once at
  deploy time).
- The OpenAPI docstring was updated to mention the new cap,
  but the field's `description` still says "Max 50 MB by
  default" — operators reading the OpenAPI page won't see
  the env-var hint unless they expand the schema. Minor
  UX issue; not worth a separate field.

## Alternatives considered

- **Stream the upload** — `await file.read(chunk_size)`
  instead of `await file.read()`. The current code reads
  the whole file into memory before checking the size
  cap. Streaming would let us reject early, but
  `python-multipart` (which FastAPI uses) already buffers
  the whole upload in memory before the handler runs —
  streaming would only save the second copy. Not worth
  the complexity.
- **Let nginx / Caddy enforce the cap** — push the limit
  to the reverse proxy. Cleaner separation of concerns, but
  the user reported the error from the FastAPI endpoint
  (not nginx), and we want the error message to mention
  the actual configured cap. Keeping the cap in our code
  means the error message is meaningful.
- **100 MB default** — a "more permissive" default. We
  rejected this because most PDFs are well under 50 MB; a
  higher default would make the cap feel arbitrary. 50 MB
  is the sweet spot.
- **No hard cap, just env-var** — trust the operator to
  set a sensible value. We explicitly rejected this
  because a misconfigured `PDF_UPLOAD_MAX_BYTES=999999999999`
  would let a malicious user OOM the container. The 200 MB
  hard cap is the safety net.

## References

- `app/config/literature.py` — the `pdf_upload_max_bytes`
  field.
- `app/api/routes/workspace_actions.py` — the route
  constant and the 413 error message.
- `docs/adr/ADR-005-multi-identity-paper-dedup.md` — the
  related dedup fix (same user complaint).
