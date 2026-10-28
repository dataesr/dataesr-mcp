"""Read-only access to the tableaux repository on GitHub.

The repository owns the prototyping content (guidance, templates, index, schema);
this module only fetches it.
"""

import os
import time
import httpx

DEFAULT_REPO = "dataesr/tableaux"
DEFAULT_REF = "staging"
CACHE_TTL_SECONDS = 300
API_URL = "https://api.github.com"


class RepoError(RuntimeError):
    """Raised when a repository resource cannot be fetched."""


def _clean(path: str) -> str:
    path = path.strip().lstrip("/")
    if not path or any(part in ("", "..") for part in path.rstrip("/").split("/")):
        raise RepoError(f"Invalid repository path: {path!r}")
    return path


class GitHubRepo:
    def __init__(
        self,
        repo: str | None = None,
        ref: str | None = None,
        token: str | None = None,
        ttl: int = CACHE_TTL_SECONDS,
    ):
        self.repo = repo or os.environ.get("TABLEAUX_REPO", DEFAULT_REPO)
        self.ref = ref or os.environ.get("TABLEAUX_REF", DEFAULT_REF)
        self._token = token or os.environ.get("GITHUB_TOKEN")
        self._ttl = ttl
        self._cache: dict[tuple[str, str], tuple[float, object]] = {}

    def _headers(self, accept: str) -> dict[str, str]:
        headers = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _request(self, path: str, accept: str) -> httpx.Response:
        url = f"{API_URL}/repos/{self.repo}/contents/{path}"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, params={"ref": self.ref}, headers=self._headers(accept))
        if response.status_code == 404:
            raise RepoError(f"{path} not found in {self.repo}@{self.ref}")
        if response.status_code in (401, 403):
            raise RepoError(
                f"GitHub refused access to {self.repo} ({response.status_code}); " "check GITHUB_TOKEN and its rate limit"
            )
        if response.status_code >= 400:
            raise RepoError(f"GitHub returned {response.status_code} for {path}")
        return response

    def _cached(self, kind: str, path: str):
        entry = self._cache.get((kind, path))
        if entry and time.monotonic() - entry[0] < self._ttl:
            return entry[1]
        return None

    def _store(self, kind: str, path: str, value):
        self._cache[(kind, path)] = (time.monotonic(), value)
        return value

    async def get_file(self, path: str) -> str:
        path = _clean(path)
        cached = self._cached("file", path)
        if cached is not None:
            return cached
        response = await self._request(path, "application/vnd.github.raw+json")
        return self._store("file", path, response.text)

    async def list_files(self, directory: str) -> list[str]:
        """Return every file path under a directory, recursively."""
        directory = _clean(directory).rstrip("/")
        cached = self._cached("dir", directory)
        if cached is not None:
            return cached
        response = await self._request(directory, "application/vnd.github+json")
        entries = response.json()
        if not isinstance(entries, list):
            raise RepoError(f"{directory} is not a directory")
        files: list[str] = []
        for entry in entries:
            if entry["type"] == "dir":
                files.extend(await self.list_files(entry["path"]))
            elif entry["type"] == "file":
                files.append(entry["path"])
        return self._store("dir", directory, sorted(files))
