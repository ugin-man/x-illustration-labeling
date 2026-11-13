"""Classify Git responses without exposing URLs, headers, or credentials."""
from email.utils import parsedate_to_datetime
import json
import random
import re
import sys
import time

RETRYABLE = {'transient_network', 'http_access_response', 'rate_limit'}


def failure_details(stderr, now=None):
    now = time.time() if now is None else now
    raw = stderr.decode('utf-8', 'replace') if isinstance(stderr, bytes) else str(stderr)
    # Network subprocess results have already been projected to these fields.
    try:
        fixed = json.loads(raw)
        if isinstance(fixed, dict) and fixed.get('git_transport_metadata') is True:
            return fixed
    except (ValueError, TypeError):
        pass
    text = raw.lower()
    codes = re.findall(r'(?:http(?:/\d(?:\.\d)?)?[ :]+|returned error:\s*|response(?: code)?[ :]+)([1-5]\d\d)\b', text)
    code = int(codes[-1]) if codes else None
    delay = 0.0
    for value in re.findall(r'(?:recv header:\s*)?retry-after:\s*([^\r\n]+)', raw, re.I):
        try:
            seconds = float(value.strip())
        except ValueError:
            try:
                seconds = parsedate_to_datetime(value.strip()).timestamp() - now
            except (ValueError, TypeError, OverflowError):
                continue
        delay = max(delay, seconds)
    remaining_zero = bool(re.search(r'x-ratelimit-remaining:\s*0\b', text))
    if remaining_zero:
        resets = re.findall(r'x-ratelimit-reset:\s*(\d+)', text)
        if resets:
            delay = max(delay, int(resets[-1]) - now)
    if code == 429 or remaining_zero or any(x in text for x in ('rate limit', 'secondary rate', 'too many requests', 'abuse detection')):
        category = 'rate_limit'
    elif code in (401, 403):
        # The production incident recovered with the SAME credentials. A lone
        # HTTP status does not establish a permanent authorization failure.
        category = 'http_access_response'
    elif any(x in text for x in ('authentication failed', 'could not read username', 'permission denied',
                                 'repository not found', 'bad credentials', 'access denied')):
        category = 'access'
    elif code in (408, 500, 502, 503, 504) or any(x in text for x in (
            'could not resolve', 'failed to connect', 'connection reset', 'connection timed out',
            'timed out', 'timeout', 'remote end hung up', 'early eof', 'http/2 stream', 'internal server error',
            'ssl_error_syscall', 'gnutls recv error', 'recv failure', 'send failure',
            'empty reply from server', 'connection closed', 'tls connection was non-properly terminated')):
        category = 'transient_network'
    else:
        category = 'other'
    return dict(git_transport_metadata=True, category=category, http_status=code,
                retry_after_seconds=max(0.0, delay))


def retry_delay(info, attempt):
    if info['category'] in {'http_access_response', 'rate_limit'}:
        # Includes ambiguous 403 responses: back off instead of rapid polling.
        ordinary = min(60 * 2 ** attempt, 300)
    else:
        ordinary = min(2 ** attempt, 8)
    return max(info.get('retry_after_seconds', 0), ordinary) + random.uniform(0, 1)


def wait_for_retry(info, attempt, operation):
    remaining = retry_delay(info, attempt)
    while remaining > 0:
        print(json.dumps(dict(status='git_retry_wait', operation=operation,
            category=info['category'], http_status=info.get('http_status'),
            attempt=attempt + 1, remaining_seconds=round(remaining, 1))), file=sys.stderr, flush=True)
        step = min(30, remaining)
        time.sleep(step)
        remaining -= step
