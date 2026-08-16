import secrets
import threading


def check_password(password, expected):
    return secrets.compare_digest(password, expected)


class SessionStore:
    """Houdt geldige sessie-tokens in-memory bij. Geen persistentie nodig:
    een herstart van de backend logt iedereen uit, prima voor dit
    hobbyproject. Lock omdat FastAPI requests op verschillende threads
    kunnen landen."""

    def __init__(self):
        self._tokens = set()
        self._lock = threading.Lock()

    def create(self):
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._tokens.add(token)
        return token

    def is_valid(self, token):
        with self._lock:
            return token in self._tokens

    def revoke(self, token):
        with self._lock:
            self._tokens.discard(token)
