"""Verify short-lived, service-only XMUMDorm identity assertions."""
import base64
import hashlib
import hmac
import json
import re
import time

import config


def _decode(part):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", part):
        raise ValueError("Invalid encoding")
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def verify_assertion(token: str, *, now=None) -> str:
    """Return a namespaced identity; never accept an unsigned client identity."""
    secret = config.XMUMDORM_SHARED_SECRET
    if len(secret) < 32:
        raise RuntimeError("XMUMDorm integration is not configured")
    if not isinstance(token, str) or len(token) > 4096:
        raise ValueError("Invalid assertion")
    try:
        head, body, signature = token.split(".")
        expected = hmac.new(secret.encode(), f"{head}.{body}".encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _decode(signature)):
            raise ValueError("Invalid signature")
        header = json.loads(_decode(head))
        claims = json.loads(_decode(body))
        if not isinstance(header, dict) or header.get("alg") != "HS256" or header.get("typ") != "JWT":
            raise ValueError("Invalid algorithm")
        if not isinstance(claims, dict) or claims.get("iss") != "xmumdorm" or claims.get("aud") != "campus-copilot":
            raise ValueError("Invalid audience")
        issued, expires = claims.get("iat"), claims.get("exp")
        clock = time.time() if now is None else now
        if (type(issued) is not int or type(expires) is not int or issued > clock + 5
                or expires <= clock or expires <= issued or expires - issued > 120):
            raise ValueError("Invalid validity period")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not re.fullmatch(r"[1-9][0-9]{0,15}", subject):
            raise ValueError("Invalid subject")
        if int(subject) > 9007199254740991:
            raise ValueError("Invalid subject")
        return "xmumdorm:" + subject
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise ValueError("Invalid assertion") from exc
