"""Muse Spark client with request provenance (new wrapper; src/llm_search.py's chat() is left unchanged).

    from muse_client import chat_logged
    content, prov = chat_logged(messages, seed=0)

prov = {ts_utc, endpoint, model_requested, model (as returned by the API), response_id (the response JSON 'id'),
        request_id (x-request-id / request-id header if the server sends one), http_status, latency_s, attempts, usage}.
The API key is read from MUSE_API_KEY and is never printed or stored.
"""
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.request

BASE_URL = os.environ.get("MUSE_BASE_URL", "https://api.meta.ai/v1")
MODEL = os.environ.get("MUSE_MODEL", "muse-spark-1.3")
ENDPOINT = BASE_URL.rstrip("/") + "/chat/completions"
REQ_ID_HEADERS = ("x-request-id", "request-id", "x-amzn-requestid", "x-fb-request-id", "x-fb-trace-id", "cf-ray")


def _redact(s):
    k = os.environ.get("MUSE_API_KEY") or ""
    return s.replace(k, "[REDACTED]") if k else s


def chat_logged(messages, seed=0, max_tokens=16000, retries=3, json_mode=True, timeout=240):
    """POST one chat completion; returns (content, provenance dict). Raises RuntimeError after `retries` failures."""
    key = os.environ.get("MUSE_API_KEY")
    if not key:
        raise RuntimeError("MUSE_API_KEY not set (copy .env.example to .env and fill it in, or export it)")
    last = None
    for a in range(retries):
        payload = {"model": MODEL, "messages": messages, "max_tokens": max_tokens, "seed": seed + 7919 * a}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        req = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        ts = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                status, hdrs, d = r.status, {k.lower(): v for k, v in r.headers.items()}, json.loads(r.read())
            lat = time.perf_counter() - t0
            content = d["choices"][0]["message"].get("content")
            if not content:
                raise ValueError(f"empty content, finish_reason={d['choices'][0].get('finish_reason')}")
            if json_mode:
                json.loads(content)
            rid = next((hdrs[h] for h in REQ_ID_HEADERS if h in hdrs), None)
            prov = dict(ts_utc=ts, endpoint=ENDPOINT, model_requested=MODEL, model=d.get("model"),
                        response_id=d.get("id"), request_id=rid, request_id_header=next(
                            (h for h in REQ_ID_HEADERS if h in hdrs), None), http_status=status,
                        latency_s=round(lat, 2), attempts=a + 1, usage=d.get("usage", {}),
                        finish_reason=d["choices"][0].get("finish_reason"))
            return content, prov
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {_redact(e.read().decode(errors='replace')[:300])}"
        except Exception as e:  # noqa: BLE001
            last = _redact(f"{type(e).__name__}: {e}")
        print(f"  Muse call failed (attempt {a + 1}): {last}", flush=True)
        if "content_policy" in last or "HTTP 401" in last or "HTTP 403" in last:
            break
        time.sleep(3 * (a + 1))
    raise RuntimeError(last)
