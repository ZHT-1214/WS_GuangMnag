"""Small Tencent Cloud one-sentence ASR client for 16 kHz mono WAV audio."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


HOST = "aai.tencentcloudapi.com"
URL = "https://" + HOST


def configured() -> bool:
    return bool(os.getenv("WSPLUS_TENCENT_SECRET_ID") and os.getenv("WSPLUS_TENCENT_SECRET_KEY"))


def transcribe_wav(audio: bytes) -> str:
    if not configured():
        raise RuntimeError("Tencent ASR credentials are not configured")
    if not audio or len(audio) > 1024 * 1024:
        raise ValueError("WAV audio must be between 1 byte and 1 MB")

    secret_id = os.environ["WSPLUS_TENCENT_SECRET_ID"]
    secret_key = os.environ["WSPLUS_TENCENT_SECRET_KEY"]
    fields = {
        "Action": "SentenceRecognition",
        "Version": "2018-05-22",
        "Region": os.getenv("WSPLUS_TENCENT_REGION", "ap-guangzhou"),
        "ProjectId": 0,
        "SubServiceType": 2,
        "EngSerViceType": "16k",
        "VoiceFormat": "wav",
        "UsrAudioKey": uuid.uuid4().hex,
        "Timestamp": int(time.time()),
        "Nonce": random.randint(100000, 999999999),
        "SecretId": secret_id,
        "SourceType": 1,
        "DataLen": len(audio),
        "Data": base64.b64encode(audio).decode("ascii"),
    }
    canonical = "POST%s/?%s" % (
        HOST,
        "&".join("%s=%s" % pair for pair in sorted(fields.items())),
    )
    signature = base64.b64encode(
        hmac.new(secret_key.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha1).digest()
    ).decode("ascii")
    fields["Signature"] = signature
    body = urllib.parse.urlencode(fields).encode("ascii")
    request = urllib.request.Request(
        URL,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "Host": HOST,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError("Tencent ASR request failed (HTTP %s)" % error.code) from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError("Tencent ASR service is unreachable") from error

    response = result.get("Response", {})
    if response.get("Error"):
        error = response["Error"]
        raise RuntimeError("Tencent ASR error: %s" % error.get("Code", "unknown"))
    text = str(response.get("Result", "")).strip()
    if not text:
        raise RuntimeError("Tencent ASR returned no recognized speech")
    return text
