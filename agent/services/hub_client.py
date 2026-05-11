import json
import urllib.error
import urllib.request


def post_json(url: str, payload: dict, token: str | None = None, timeout: int = 5) -> dict:
    """POST a JSON payload and return a small result object.

    The client is intentionally standard-library only to avoid adding a new
    dependency to the agent installer.
    """
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'

    data = json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(url, data=data, headers=headers, method='POST')

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode('utf-8', errors='replace')
            return {
                'ok': 200 <= response.status < 300,
                'status': response.status,
                'body': body,
            }
    except urllib.error.HTTPError as exc:
        return {
            'ok': False,
            'status': exc.code,
            'body': exc.read().decode('utf-8', errors='replace'),
        }
    except Exception as exc:
        return {
            'ok': False,
            'status': None,
            'body': str(exc),
        }
