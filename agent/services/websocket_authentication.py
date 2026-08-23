import json


class HubAuthenticationError(ConnectionError):
    pass


class ReconnectBackoff:
    def __init__(self, initial_seconds: int = 1, maximum_seconds: int = 30):
        self.initial_seconds = initial_seconds
        self.maximum_seconds = maximum_seconds
        self._next_seconds = initial_seconds

    def next_failure_delay(self) -> int:
        delay = self._next_seconds
        self._next_seconds = min(self._next_seconds * 2, self.maximum_seconds)
        return delay

    def reset_after_authentication(self) -> None:
        self._next_seconds = self.initial_seconds


def await_hello_acknowledgement(ws) -> dict:
    """Wait until the Hub has authenticated the socket before declaring it connected."""
    raw_message = ws.recv()
    if raw_message is None:
        raise HubAuthenticationError('connexion fermee avant acquittement')

    try:
        message = json.loads(raw_message)
    except (json.JSONDecodeError, TypeError) as exc:
        raise HubAuthenticationError('acquittement invalide') from exc

    if not isinstance(message, dict):
        raise HubAuthenticationError('acquittement invalide')

    if message.get('type') == 'hello_ack':
        return message

    if message.get('type') == 'error':
        code = str(message.get('code') or 'unauthorized').strip()
        raise HubAuthenticationError(f'authentification refusee ({code})')

    raise HubAuthenticationError('hello_ack absent')
