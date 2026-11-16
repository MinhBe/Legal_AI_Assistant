# Contract AU1 — upload audio/video of a consultation → local transcript → consultation cases (class A)

Spec: gap item AU1 (`docs/design/v1.1-gap.md`), design §7B.3 (self-hosted ASR, mask PII right after the
transcript, raw audio/transcript class A). Minh approved installing ffmpeg + faster-whisper (Claude adds them to the
image; you do NOT install anything). Read `AGENTS.md` first. Do not commit. Never read `.env`.
Everything here is class A: no cloud LLM, ever. Admin/dev only (AUTH1 permission `upload`).

## Files you may create or edit (nothing else)
- `backend/app/audio/__init__.py`, `convert.py`, `transcribe.py`, `cases.py`, `job.py` (new)
- `backend/app/db/models.py` (add `UploadJob` at the end)
- `backend/app/config.py` (`audio_model: str = "medium"`, `audio_device: str = "auto"`, `audio_compute: str =
  "int8"`, `audio_language: str = "vi"`, `audio_max_bytes: int = 600_000_000`, `audio_chunk_minutes: int = 5`)
- `backend/app/upload/service.py` (route audio/video files to the audio job; keep documents unchanged)
- `backend/app/api/routes.py` (only `create_upload` + one new `GET /api/uploads/{id}/job`)
- `backend/tests/test_audio.py` (new)
- `frontend/app/upload/page.tsx`, `frontend/app/globals.css` (only new `.au-*` rules)

## Flow
1. `precheck`: accept `.mp3 .m4a .wav .ogg .webm .mp4 .mov .mkv` up to `audio_max_bytes`; the form must send
   `consent=true` ("Người được ghi âm đã đồng ý cho dùng bản ghi này") — otherwise 422 with that sentence.
2. Register the upload as today (status `processing`) and create `UploadJob` (`upload_job`): `upload_id` PK,
   `kind` ("audio"), `stage` (`converting` | `transcribing` | `masking` | `extracting` | `done` | `failed`),
   `progress` float 0–1, `message` text, `duration_s` float, `consent` bool, `updated_at`.
3. Background job (`audio/job.py`, own DB session, never raises — failures set stage/status `failed`):
   - `convert.to_wav(src) -> path`: `ffmpeg -y -i src -vn -ac 1 -ar 16000 out.wav` (subprocess, no shell, timeout
     scaled to duration); `convert.duration(path)` via `ffprobe`.
   - `transcribe.run(wav, on_progress) -> list[{start, end, text}]`: `faster_whisper.WhisperModel(settings.
     audio_model, device=settings.audio_device, compute_type=settings.audio_compute)`, `language=settings.
     audio_language`, `vad_filter=True`; model loaded lazily once per process and cached; progress =
     segment.end / duration, written to the job at most every 5 s. Import `faster_whisper` inside the function so
     the app still starts without it (then the job fails with a clear message).
   - Mask: build the transcript text with time stamps `[hh:mm:ss] text`, then `app.gateway.pii.mask` on the whole
     text. Save the RAW transcript next to the file (`<sha>.raw.txt`, class A, local only) and use the MASKED text
     everywhere else (`<sha>.txt` full text, ingest, LLM).
   - Ingest the masked transcript with the existing `ingest_upload` but split into chunks of
     `audio_chunk_minutes` (section headings `Đoạn hh:mm:ss–hh:mm:ss`) so nodes stay small.
   - `cases.extract(router, chunk_text) -> list[{situation, question, answer, articles}]`: one local call per chunk
     inside `data_class_scope("A")` (`router.extract_json(..., task="route")`), strict JSON schema in the prompt,
     invalid items dropped; for each case add a node (level `case`, heading `Ca tư vấn {n} ({hh:mm:ss})`, text =
     the four fields in Vietnamese) to the same upload document and `node_reference`s to law nodes found by
     `references.extract_refs(..., known_docs=known_docs_from_db(db))` in `articles` + `answer` (existing nodes
     only). Progress during extraction = chunks done / chunks.
   - End: upload status `pending_review` (same review flow as documents), job stage `done`.
4. `GET /api/uploads/{id}/job` → the job row (404 when none). The upload list shows audio rows like documents.

## Frontend `/upload`
- Accept audio/video in the file picker and drop zone; for these files show a required consent checkbox before
  sending. Rows with a job show stage (Việt hoá: Đang chuyển định dạng / Đang chép lời / Đang che dữ liệu cá nhân
  / Đang rút ca tư vấn / Xong) and a progress bar polling `/job` every 3 s; "Xem toàn văn" shows the masked
  transcript; "Xem node" shows the cases.

## Tests (`tests/test_audio.py`; no real model, no real audio decoding unless ffmpeg is present)
1. `precheck` accepts the audio/video suffixes, rejects without consent, rejects over the size limit.
2. Job with monkeypatched `convert` and `transcribe` (fake segments containing a fake name + phone and
   "khoản 1 Điều 36 Bộ luật Lao động"): raw file keeps the name, masked text and every node do not; chunk
   headings present; a fake router returns 1 case per chunk → `case` nodes created and a `node_reference` to
   `blld2019-d36-k1`; the router saw data class "A" on every call; upload ends `pending_review`, job `done`.
3. Failure in transcription → upload `failed`, job `failed` with message; no exception escapes.
4. If `ffmpeg` exists on PATH: generate a 2-second silent wav with ffmpeg, `convert.to_wav` + `duration` work
   (skip otherwise).

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_audio.py tests/test_upload_api.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api python -m scripts.eval_gate
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/audio app/upload app/api/routes.py app/db/models.py app/config.py tests/test_audio.py
docker compose exec -T web npx tsc --noEmit
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
