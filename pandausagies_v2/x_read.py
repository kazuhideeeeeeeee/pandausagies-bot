from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib import error, parse, request


class XReadError(RuntimeError):
    def __init__(self, kind: str, retry_after: int | None = None):
        super().__init__(f"X read failed: {kind}")
        self.kind, self.retry_after = kind, retry_after


class ReadTransport(Protocol):
    def get(self, url: str, headers: dict[str, str], timeout: int) -> tuple[int, dict[str, str], bytes]: ...


class UrllibReadTransport:
    """GET-only transport. It has no mutation method by design."""
    def get(self, url: str, headers: dict[str, str], timeout: int) -> tuple[int, dict[str, str], bytes]:
        if not url.startswith("https://api.x.com/2/"):
            raise XReadError("invalid_read_endpoint")
        req = request.Request(url, method="GET", headers=headers)
        try:
            with request.urlopen(req, timeout=timeout) as response:
                return response.status, dict(response.headers.items()), response.read()
        except error.HTTPError as exc:
            raw = exc.read()  # retained in memory; never logged
            return exc.code, dict(exc.headers.items()), raw
        except (error.URLError, TimeoutError, socket.timeout):
            raise XReadError("timeout") from None


@dataclass(frozen=True)
class XPage:
    mentions: list[dict[str, Any]]
    newest_id: str | None
    next_token: str | None
    api_calls: int


class XReadClient:
    """X API v2 read-only client. No write endpoint or method is present."""
    BASE = "https://api.x.com/2"

    def __init__(self, bearer_token: str, transport: ReadTransport | None = None, timeout: int = 20):
        if not bearer_token:
            raise ValueError("X bearer token is missing")
        self._token, self._transport, self._timeout = bearer_token, transport or UrllibReadTransport(), timeout
        self.api_calls = 0

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = parse.urlencode({key:value for key,value in (params or {}).items() if value is not None})
        url = f"{self.BASE}{path}" + (f"?{query}" if query else "")
        self.api_calls += 1
        status, headers, raw = self._transport.get(url, {"Authorization":f"Bearer {self._token}","Accept":"application/json","User-Agent":"pandausagies-v2-read-only/1.0"}, self._timeout)
        if status == 429:
            retry = headers.get("retry-after") or headers.get("Retry-After")
            raise XReadError("rate_limited", int(retry) if retry and retry.isdigit() else None)
        if status in (401,403): raise XReadError("authentication" if status==401 else "permission")
        if status >= 500: raise XReadError("server")
        if status != 200: raise XReadError("http")
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise XReadError("malformed") from None
        if not isinstance(value, dict): raise XReadError("malformed")
        return value

    def lookup_user(self, username: str) -> dict[str, str]:
        clean = username.lstrip("@").strip()
        if not clean or not clean.replace("_", "").isalnum(): raise ValueError("invalid X username")
        value = self._get(f"/users/by/username/{parse.quote(clean)}", {"user.fields":"id,name,username"})
        data = value.get("data")
        if not isinstance(data, dict) or not all(data.get(k) for k in ("id","name","username")): raise XReadError("user_not_found")
        return {"id":str(data["id"]),"name":str(data["name"]),"username":str(data["username"])}

    def lookup_post(self, post_id: str) -> dict[str, Any] | None:
        try: value = self._get(f"/posts/{parse.quote(str(post_id))}", {"post.fields":"id,author_id,conversation_id,created_at,text"})
        except XReadError as exc:
            if exc.kind == "http": return None
            raise
        return value.get("data") if isinstance(value.get("data"),dict) else None

    def get_mentions(self, user_id: str, since_id: str | None = None, max_results: int = 10, max_pages: int = 2, total_limit: int = 20) -> XPage:
        per_page = max(5,min(100,max_results)); pages=max(1,min(5,max_pages)); limit=max(1,min(100,total_limit))
        token=None; collected=[]; newest=None
        for _ in range(pages):
            params={"max_results":per_page,"since_id":since_id,"pagination_token":token,"expansions":"author_id","post.fields":"id,text,author_id,created_at,conversation_id,in_reply_to_user_id,referenced_posts","user.fields":"id,name,username"}
            value=self._get(f"/users/{parse.quote(str(user_id))}/mentions",params)
            users={str(u.get("id")):u for u in value.get("includes",{}).get("users",[]) if isinstance(u,dict)}
            for post in value.get("data") or []:
                if not isinstance(post,dict): continue
                author=users.get(str(post.get("author_id")),{})
                refs=post.get("referenced_posts") or []
                collected.append({"x_post_id":str(post.get("id","")),"author_id":str(post.get("author_id","")),"username":str(author.get("username","")),"display_name":str(author.get("name","")),"text":str(post.get("text","")),"created_at":str(post.get("created_at","")),"conversation_id":str(post.get("conversation_id") or post.get("id") or ""),"referenced_post_id":str(refs[0].get("id","")) if refs and isinstance(refs[0],dict) else "","in_reply_to_user_id":str(post.get("in_reply_to_user_id") or ""),"raw_minimal":{"referenced_type":str(refs[0].get("type","")) if refs and isinstance(refs[0],dict) else ""}})
                if len(collected)>=limit: break
            meta=value.get("meta") if isinstance(value.get("meta"),dict) else {}
            newest=newest or (str(meta.get("newest_id")) if meta.get("newest_id") else None)
            token=str(meta.get("next_token")) if meta.get("next_token") else None
            if len(collected)>=limit or not token: break
        collected.sort(key=lambda item:(item.get("created_at",""),int(item["x_post_id"]) if item.get("x_post_id","").isdigit() else 0))
        return XPage(collected,newest,token,self.api_calls)


OPTOUT = ("自動返信しないで","自動で返さないで","bot返信不要","no automated replies","opt out")
SENSITIVE = {"self_harm":("死にたい","自殺","自傷"),"medical":("診断して","薬を","病気です"),"legal":("法律相談","訴えたい"),"money":("お金を貸して","送金して"),"violence":("殺す","殴る"),"sexual":("性的","セックス"),"hate":("差別","ヘイト")}
SPAM = ("今すぐ稼げる","フォロバ100","click here","無料プレゼント","仮想通貨を送")


def classify_mention(text: str) -> tuple[str, bool]:
    lowered=text.casefold()
    if any(term.casefold() in lowered for term in OPTOUT): return "opted_out",True
    if any(term.casefold() in lowered for terms in SENSITIVE.values() for term in terms): return "needs_human",False
    if any(term.casefold() in lowered for term in SPAM): return "spam",False
    if not text.strip(): return "ignore",False
    return "candidate",False


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
