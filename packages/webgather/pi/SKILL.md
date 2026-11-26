---
name: webgather
description: Collect public web content under a compliance gate that refuses (never bypasses) login walls, CAPTCHAs, robots.txt disallows, private groups/profiles and rate limits, then returns de-identified text. Use when asked to fetch, scrape or gather a public web page or a list of URLs.
---

# webgather

All work goes through the `webgather` CLI. It prints one JSON object on stdout.
Exit code: `0` allowed/ok, `2` the gate blocked, `1` usage error.

1. Preview a decision without fetching: `webgather check <url>`.
   Show the user `decision.reason`. If blocked, stop — do not look for another way.
2. Fetch one allowed URL: `webgather collect <url>`. The returned `text` is
   already de-identified. Add `--no-mask` only if the user explicitly asks for raw text.

Rules — these are hard limits, not preferences:
- Never try to get around a block. There is no fake user-agent, proxy, cookie,
  stored session or CAPTCHA step, and you must not add one.
- Never fetch a private group, a personal profile, or messages. The gate already
  refuses these; do not route around it.
- Never log in on the user's behalf or use their cookies/token to reach content.
- One URL at a time, honouring the gate's rate limit. If `check` says
  `rate_limited`, wait the stated seconds; do not hammer.
- A host with no policy is treated cautiously (robots respected, 5s delay). To
  collect at scale from a specific site, ask the user to confirm its terms and
  add a `SourcePolicy` with the legal basis on one line.

When the task is a list of URLs, run `check` on each first, collect only the
allowed ones, and report the blocked ones with their reason so the user sees what
was skipped and why.
