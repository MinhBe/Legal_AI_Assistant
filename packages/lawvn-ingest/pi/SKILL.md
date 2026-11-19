---
name: lawvn-ingest
description: Bring media (videos, audio) from a registered source adapter into the LawVN recording inbox, then send it through the Kaggle transcription and PII-masking pipeline. Use when asked to import, fetch or queue recordings or videos for LawVN.
---

# lawvn-ingest

All work goes through the `lawvn-ingest` CLI. It prints one JSON object on stdout.

1. See which adapters exist: `lawvn-ingest adapters`.
2. Preview before fetching: `lawvn-ingest fetch --adapter <name> --opt key=value --dry-run`.
   Show the user the item count and captions, then fetch without `--dry-run`.
3. Queue for transcription and masking: `lawvn-ingest push`. When the Kaggle kernels finish,
   `lawvn-ingest push --collect` downloads the masked transcripts only.

Rules:
- Every item carries `consent` (`own`, `licensed` or `public-official`). The store refuses any
  other value. Do not set `consent` for content the user has not said they own or are licensed
  to use.
- Raw media and unmasked captions stay on the user's machine. Only masked transcripts may go to
  an external model.
- Do not read, print or copy token files (for example `keys/facebook_user_token.txt`).
- Heavy work (ASR, masking) runs on Kaggle, never locally.

Adapter options:
- `folder`: `path=<dir>`, `consent=own|licensed|public-official`.
- `fb-dyi`: `path=<zip or folder with facebook-*.zip>`.
- `fb-graph`: `token_file=<path>` (default `keys/facebook_user_token.txt`).
