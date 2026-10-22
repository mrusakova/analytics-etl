"""Клиент REST API «Мой Класс» (синхронный): токен, повторы при 401/429/сбоях, постраничная выгрузка."""
import time
import httpx

BASE_URL = "https://api.moyklass.com/v1"


class MoyKlass:
    def __init__(self, api_key: str, http: httpx.Client | None = None):
        self._key = api_key
        self._token = None
        self._http = http or httpx.Client(base_url=BASE_URL, timeout=30)

    def _auth(self):
        r = self._http.post("/company/auth/getToken", json={"apiKey": self._key})
        r.raise_for_status()
        self._token = r.json()["accessToken"]

    def get(self, path: str, **params):
        params = {k: v for k, v in params.items() if v is not None}
        for attempt in range(6):
            if not self._token:
                self._auth()
            try:
                r = self._http.get(path, params=params, headers={"x-access-token": self._token})
            except httpx.TransportError:
                time.sleep(1.5 * (attempt + 1)); continue
            if r.status_code == 401:
                self._token = None; continue
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After") or 2 * (attempt + 1))); continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"Мой Класс: не удалось выполнить GET {path}")

    def paged(self, path: str, key: str | None = None, limit: int = 500, **params):
        """Вся выгрузка списка. key — ключ списка в ответе (joins, lessons, ...), None если ответ — список."""
        out, offset = [], 0
        while True:
            data = self.get(path, limit=limit, offset=offset, **params)
            items = data if key is None else data[key]
            out.extend(items)
            if len(items) < limit:
                return out
            offset += limit
