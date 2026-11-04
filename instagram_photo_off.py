"""Experimental Instagram profile expansion OFF request; Python 3.9+.
Derived from supplied Instagram 312 APK and HideFollow (1).py.
Uses HideFollow's session-to-IGT bearer construction and User-Agent.
No claim that this authentication is accepted by the REST endpoint.
A fresh random _uuid is an experimental client ID, NOT the phone's real ID.
No files/secrets are saved. One request, no automatic retry or redirects.
Normal run: hidden session prompt, then type OFF to send.
--self-test: offline only. API acknowledgement still requires manual verification.
"""
import argparse
import base64
import getpass
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
import warnings

ENDPOINT = 'https://i.instagram.com/api/v1/users/update_profile_picture_expansion_setting/'
FIELD = 'enable_profile_picture_expansion'
LIMIT = 65536


def hidden(prompt):
    # Fail closed if getpass cannot suppress echo (e.g. some IDE consoles).
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        return getpass.getpass(prompt).strip()

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('Redirect blocked.')

def send_once(request):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        response = opener.open(request, timeout=20)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.code, response.read(LIMIT + 1)

def summarize(code, raw):
    """Only fixed labels and bounded HTTP code are exposed. No raw strings."""
    out = {'http_status': code if type(code) is int and 100 <= code <= 599 else 'unknown',
           'api_status': 'unknown', 'result': 'NOT_VERIFIED'}
    if len(raw) > LIMIT:
        out['response'] = 'too_large'
        return out
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        out['response'] = 'invalid_json'
        return out
    if not isinstance(obj, dict):
        out['response'] = 'not_an_object'
        return out
    status = obj.get('status')
    if status in ('ok', 'fail'):
        out['api_status'] = status
    if type(code) is int and 200 <= code < 300 and status == 'ok':
        out['result'] = 'ACKNOWLEDGED_NOT_VERIFIED'
    elif status == 'fail' or (type(code) is int and code >= 400):
        out['result'] = 'REJECTED'
    # Never echo arbitrary response text, URLs, IDs or headers.
    known = {'login_required', 'challenge_required', 'checkpoint_required',
             'feedback_required', 'rate_limit_error', 'sentry_block',
             'consent_required', 'invalid_parameters', 'invalid_request',
             'csrf_failed', 'user_has_logged_out'}
    for key in ('error_type', 'message'):
        value = obj.get(key)
        out[key] = value if isinstance(value, str) and value in known else ('present_withheld' if key in obj else 'absent')
    out['challenge_present'] = bool(obj.get('challenge') or obj.get('checkpoint_url'))
    out['status_code_present'] = 'status_code' in obj
    return out

def build_request(session):
    if (not session or len(session) > 8192 or
            any(ord(c) <= 32 or ord(c) >= 127 or c in ';,"\\' for c in session)):
        raise ValueError('Invalid session cookie.')
    match = re.fullmatch(r'([1-9][0-9]*)(?::|%3[aA]).+', session)
    if not match:
        raise ValueError('Unrecognized session format.')
    uid = match.group(1)
    token = base64.b64encode(json.dumps({
        'ds_user_id': uid, 'sessionid': session,
        'should_use_header_over_cookies': True,
    }, separators=(',', ':')).encode()).decode('ascii')
    installation_id = str(uuid.uuid4())
    headers = {
        'Authorization': 'Bearer IGT:2:' + token,
        'Cookie': 'sessionid=' + session + '; ds_user_id=' + uid,
        'IG-INTENDED-USER-ID': uid,
        'X-IG-App-ID': '124024574287414',
        'X-Auth-Type': 'instagram',
        'User-Agent': 'Instagram 453.0.0',
        'X-IG-Device-ID': installation_id,
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Accept': 'application/json',
        'Accept-Encoding': 'identity',
    }
    data = urllib.parse.urlencode({FIELD: 'false', '_uuid': installation_id}).encode()
    return urllib.request.Request(ENDPOINT, data=data, headers=headers, method='POST')


def self_test():
    from unittest.mock import patch
    secret = '123%3ATEST_ONLY_NOT_A_REAL_SESSION'
    request = build_request(secret)
    token = request.get_header('Authorization').split('Bearer IGT:2:', 1)[1]
    decoded = json.loads(base64.b64decode(token))
    assert decoded == {'ds_user_id': '123', 'sessionid': secret,
                       'should_use_header_over_cookies': True}
    body = urllib.parse.parse_qs(request.data.decode())
    assert body[FIELD] == ['false']
    assert body['_uuid'] == [request.get_header('X-ig-device-id')]
    assert set(body) == {FIELD, '_uuid'}
    assert request.method == 'POST' and request.full_url == ENDPOINT
    for invalid in ['', 'abc', '123:test; other=x', '123:test\r\nX: value']:
        try: build_request(invalid)
        except ValueError: pass
        else: raise AssertionError('Invalid cookie accepted')
    assert summarize(200, b'{"status":"fail"}')['result'] == 'REJECTED'
    assert summarize(200, b'{"status":"ok"}')['result'] == 'ACKNOWLEDGED_NOT_VERIFIED'
    assert summarize(500, b'{"status":"ok"}')['result'] == 'REJECTED'
    assert summarize(200, b'<html>')['response'] == 'invalid_json'
    assert summarize(200, b'x'*(LIMIT+1))['response'] == 'too_large'
    output = json.dumps(summarize(200, json.dumps({'status': secret,
                         'message': token, 'error_type': secret}).encode()))
    assert secret not in output and token not in output
    for code in (301, 302, 303, 307, 308):
        try: NoRedirect().redirect_request(request, None, code, '', {}, 'https://example.invalid')
        except RuntimeError: pass
        else: raise AssertionError('Redirect permitted')
    class Response:
        code = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, count): return b'{"status":"fail"}'
    with patch('urllib.request.OpenerDirector.open', return_value=Response()) as mocked:
        assert send_once(request) == (200, b'{"status":"fail"}')
        assert mocked.call_count == 1
    print('PASS: offline tests only. No live request sent.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not sys.stdin.isatty():
        print('Open this script in PowerShell or a local terminal. Piped input is refused.')
        return 2
    print('Instagram profile photo expansion: request OFF (experimental).')
    print('Uses a new test client ID, not your phone installation ID.')
    print('Only your sessionid is needed. Input stays hidden; nothing is saved.')
    session = hidden('Paste your sessionid value, then press Enter: ')
    request = build_request(session)
    if input('Type OFF to send ONE request: ').strip() != 'OFF':
        print('Cancelled. Nothing sent.')
        return 0
    code, raw = send_once(request)
    result = summarize(code, raw)
    print(json.dumps(result, indent=2))
    print('Reopen the Instagram setting and test from another account.')
    print('ACKNOWLEDGED_NOT_VERIFIED means API accepted, not verified visible behavior.')
    print('Do not retry repeatedly if rejected.')
    return 0 if result['result'] == 'ACKNOWLEDGED_NOT_VERIFIED' else 1


if __name__ == '__main__':
    try:
        code = main()
    except (KeyboardInterrupt, EOFError):
        print('Interrupted. If sending had started, outcome is unknown.')
        code = 2
    except Exception:
        print('Stopped: invalid input, hidden-input failure, redirect or network failure.')
        print('Details withheld to protect session data. If sending began, check the app before retrying.')
        code = 2
    if sys.stdin.isatty() and '--self-test' not in sys.argv:
        try: input('Press Enter to close...')
        except (KeyboardInterrupt, EOFError): pass
    sys.exit(code)
