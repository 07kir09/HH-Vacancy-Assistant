from __future__ import annotations

import json
import time
from typing import Any, Callable
from urllib.parse import urlencode

import requests


class HHApiError(RuntimeError):
    def __init__(self, status_code: int, message: str, payload: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload

    def __str__(self) -> str:
        if self.payload is None:
            return f"{self.args[0]} (status={self.status_code})"
        if isinstance(self.payload, (dict, list)):
            details = json.dumps(self.payload, ensure_ascii=False)
        else:
            details = str(self.payload)
        return f"{self.args[0]} (status={self.status_code}, details={details})"


TokenUpdater = Callable[[dict[str, Any]], None]


class HHApiClient:
    def __init__(
        self,
        *,
        base_url: str,
        token_url: str,
        auth_url: str,
        user_agent: str,
        client_id: str | None = None,
        client_secret: str | None = None,
        access_token: str | None = None,
        refresh_token: str | None = None,
        expires_at: float | None = None,
        token_updater: TokenUpdater | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token_url = token_url
        self.auth_url = auth_url
        self.client_id = client_id.strip() if isinstance(client_id, str) else client_id
        self.client_secret = client_secret.strip() if isinstance(client_secret, str) else client_secret
        self.access_token = access_token.strip() if isinstance(access_token, str) else access_token
        self.refresh_token = refresh_token.strip() if isinstance(refresh_token, str) else refresh_token
        self.expires_at = expires_at
        self.token_updater = token_updater
        self.session = requests.Session()
        self.session.headers.update(
            {
                "HH-User-Agent": user_agent,
                "User-Agent": user_agent,
                "Accept": "application/json",
            }
        )

    def authorization_url(self, redirect_uri: str, state: str | None = None) -> str:
        if not self.client_id:
            raise ValueError("HH_CLIENT_ID is required")
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
        }
        if state:
            params["state"] = state
        return f"{self.auth_url}?{urlencode(params)}"

    def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        if not self.client_id or not self.client_secret:
            raise ValueError("HH_CLIENT_ID and HH_CLIENT_SECRET are required")
        payload = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }
        token = self._token_request(payload)
        self._set_token(token)
        return token

    def get_application_token(self) -> dict[str, Any]:
        if not self.client_id or not self.client_secret:
            raise ValueError("HH_CLIENT_ID and HH_CLIENT_SECRET are required")
        token = self._token_request(
            {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
        )
        self._set_token(token)
        return token

    def refresh_access_token(self) -> dict[str, Any]:
        if not self.refresh_token:
            raise HHApiError(401, "No refresh token is available")
        if not self.client_id or not self.client_secret:
            raise ValueError("HH_CLIENT_ID and HH_CLIENT_SECRET are required to refresh token")
        token = self._token_request(
            {
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
            }
        )
        self._set_token(token)
        return token

    def _token_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(self.token_url, data=payload, timeout=30)
        if response.status_code >= 400:
            raise HHApiError(response.status_code, "OAuth token request failed", self._payload(response))
        data = response.json()
        data["expires_at"] = time.time() + int(data.get("expires_in", 0) or 0)
        return data

    def _set_token(self, token: dict[str, Any]) -> None:
        self.access_token = token.get("access_token")
        self.refresh_token = token.get("refresh_token", self.refresh_token)
        self.expires_at = token.get("expires_at")
        if self.token_updater:
            self.token_updater(token)

    def _headers(self, auth: bool) -> dict[str, str]:
        if not auth or not self.access_token:
            return {}
        return {"Authorization": f"Bearer {self.access_token}"}

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | list[tuple[str, Any]] | None = None,
        data: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        auth: bool = True,
        retry: bool = True,
    ) -> Any:
        if auth and self.refresh_token and self.expires_at and time.time() > self.expires_at - 60:
            self.refresh_access_token()
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        response = self.session.request(
            method,
            url,
            params=params,
            data=data,
            json=json,
            headers=self._headers(auth),
            timeout=30,
        )
        if response.status_code == 401 and retry and self.refresh_token:
            self.refresh_access_token()
            return self._request(method, path, params=params, data=data, json=json, auth=auth, retry=False)
        if response.status_code >= 400:
            raise HHApiError(response.status_code, f"HH API request failed: {method} {path}", self._payload(response))
        if response.status_code == 204 or not response.content:
            return None
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()
        return response.text

    @staticmethod
    def _payload(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return response.text

    @staticmethod
    def flatten_params(params: dict[str, Any]) -> list[tuple[str, Any]]:
        result: list[tuple[str, Any]] = []
        for key, value in params.items():
            if value is None or value == "":
                continue
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    if item is not None and item != "":
                        result.append((key, item))
            else:
                result.append((key, value))
        return result

    def me(self) -> dict[str, Any]:
        return self._request("GET", "/me", auth=True)

    def search_vacancies(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._request("GET", "/vacancies", params=self.flatten_params(params), auth=bool(self.access_token))

    def get_vacancy(self, vacancy_id: str) -> dict[str, Any]:
        return self._request("GET", f"/vacancies/{vacancy_id}", auth=bool(self.access_token))

    def get_negotiations(self, *, vacancy_id: str | None = None, status: str | None = None) -> dict[str, Any]:
        params = {"vacancy_id": vacancy_id, "status": status}
        return self._request("GET", "/negotiations", params=self.flatten_params(params), auth=True)

    def respond_to_vacancy(self, *, vacancy_id: str, resume_id: str, message: str) -> Any:
        raise HHApiError(
            410,
            "Applicant API responses are no longer supported by hh.ru",
            {
                "vacancy_id": vacancy_id,
                "resume_id": resume_id,
                "message": "Use apply_alternate_url and manual confirmation instead.",
            },
        )
