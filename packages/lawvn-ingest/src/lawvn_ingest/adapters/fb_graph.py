"""Videos Minh uploaded to his OWN Facebook account, via the official Graph API.

Token: a user access token (user_videos) from Minh's own Meta app in Development mode, read from
a file (default RAG/keys/facebook_user_token.txt). It is only sent to graph.facebook.com and is
never printed or written anywhere.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..core import Item, stem_for

API = "https://graph.facebook.com/v23.0"
FIELDS = "id,title,description,created_time,length,source,permalink_url"


class FacebookGraph:
    name = "fb-graph"

    def __init__(self, token_file: str | None = None, session=None, token: str | None = None) -> None:
        if session is None:
            import requests

            session = requests.Session()
        self.session = session
        if token is None:
            tf = Path(token_file) if token_file else Path.cwd() / "keys" / "facebook_user_token.txt"
            if not tf.exists():
                raise FileNotFoundError(f"no token file at {tf}")
            token = tf.read_text(encoding="utf-8").strip()
        self._token = token

    def list_items(self, since=None):
        url = f"{API}/me/videos"
        params = {"type": "uploaded", "fields": FIELDS, "limit": 50, "access_token": self._token}
        if since:
            params["since"] = since
        while url:
            r = self.session.get(url, params=params, timeout=60)
            if r.status_code != 200:
                raise RuntimeError(f"Graph API {r.status_code}: {r.text[:200]}")
            body = r.json()
            for v in body.get("data", []):
                if not v.get("source"):
                    continue  # no download link (not owned by the user)
                t = datetime.strptime(v["created_time"], "%Y-%m-%dT%H:%M:%S%z")
                yield Item(id=v["id"], source="facebook-graph", consent="own", url=v["source"],
                           posted_at=t.isoformat(), caption=v.get("description", ""),
                           title=v.get("title", ""), extra={"permalink": v.get("permalink_url"),
                                                             "length_s": v.get("length")})
            url = body.get("paging", {}).get("next")
            params = None

    def fetch(self, item: Item, out_dir: Path) -> Path:
        dst = Path(out_dir) / f"{stem_for(item)}.mp4"
        with self.session.get(item.url, stream=True, timeout=600) as r:
            r.raise_for_status()
            with dst.open("wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        return dst
