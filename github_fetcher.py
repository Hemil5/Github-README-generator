import io
import os
import zipfile
import base64
from functools import lru_cache
from pathlib import PurePosixPath

import requests
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
REQUEST_TIMEOUT = 30
ARCHIVE_TIMEOUT = 120
MAX_FILE_BYTES = 160_000
MAX_FILE_EXCERPT_CHARS = 900
MAX_CONTEXT_FILES = 16

SKIP_DIRECTORIES = {
    ".git",
    ".github",
    ".next",
    ".nuxt",
    ".parcel-cache",
    ".pytest_cache",
    ".ruff_cache",
    ".svelte-kit",
    ".terraform",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "vendor",
}

SKIP_FILE_NAMES = {
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lockb",
    "uv.lock",
    "poetry.lock",
    "cargo.lock",
    "composer.lock",
    "gemfile.lock",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
}

SKIP_SUFFIXES = {
    ".csv",
    ".json",
    ".jsonl",
    ".lock",
    ".log",
    ".min.css",
    ".min.js",
    ".svg",
}

HIGH_SIGNAL_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".cs",
    ".swift",
    ".kt",
    ".scala",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".md",
    ".rst",
}

PRIORITY_FILE_NAMES = {
    "readme.md": 120,
    "readme.rst": 120,
    "main.py": 80,
    "app.py": 80,
    "index.ts": 75,
    "index.tsx": 75,
    "index.js": 75,
    "index.jsx": 75,
    "server.js": 75,
    "server.ts": 75,
    "manage.py": 70,
    "dockerfile": 40,
}


def github_headers():
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers


@lru_cache(maxsize=100)
def fetch_repo_metadata(owner, repo):
    url = f"https://api.github.com/repos/{owner}/{repo}"
    response = requests.get(url, headers=github_headers(), timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        raise Exception(f"Repo fetch failed: {response.text}")

    data = response.json()
    return {
        "owner": owner,
        "repo": repo,
        "description": data.get("description") or "Not specified in repository",
        "homepage": data.get("homepage") or "Not specified in repository",
        "topics": data.get("topics") or [],
        "default_branch": data.get("default_branch") or "main",
    }


@lru_cache(maxsize=100)
def fetch_repo_tree(owner, repo):
    metadata = fetch_repo_metadata(owner, repo)
    branch = metadata["default_branch"]
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    response = requests.get(url, headers=github_headers(), timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        raise Exception(f"Tree fetch failed: {response.text}")
    return response.json().get("tree", [])


def _download_repo_archive(owner, repo):
    metadata = fetch_repo_metadata(owner, repo)
    branch = metadata["default_branch"]
    url = f"https://api.github.com/repos/{owner}/{repo}/zipball/{branch}"
    response = requests.get(
        url,
        headers=github_headers(),
        timeout=ARCHIVE_TIMEOUT,
        allow_redirects=True,
    )
    if response.status_code != 200:
        raise Exception(f"Archive download failed: {response.text}")
    return response.content


@lru_cache(maxsize=300)
def fetch_file_content(owner, repo, path):
    metadata = fetch_repo_metadata(owner, repo)
    branch = metadata["default_branch"]
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
    response = requests.get(url, headers=github_headers(), timeout=REQUEST_TIMEOUT)
    if response.status_code != 200:
        return None

    data = response.json()
    if data.get("encoding") != "base64" or "content" not in data:
        return None

    raw_bytes = base64.b64decode(data["content"])
    if not _is_probably_text(raw_bytes):
        return None

    return raw_bytes.decode("utf-8", errors="ignore")


def _is_probably_text(raw_bytes):
    if not raw_bytes:
        return True
    if b"\x00" in raw_bytes:
        return False
    sample = raw_bytes[:4096]
    strange_bytes = sum(
        1
        for byte in sample
        if byte not in b"\n\r\t\f\b" and not 32 <= byte <= 126 and byte > 127
    )
    return strange_bytes / max(len(sample), 1) < 0.30


def _should_skip_path(relative_path):
    parts = relative_path.split("/")
    if any(part in SKIP_DIRECTORIES for part in parts[:-1]):
        return True

    file_name = parts[-1].lower()
    if file_name in SKIP_FILE_NAMES:
        return True

    if any(file_name.endswith(suffix) for suffix in SKIP_SUFFIXES):
        return True

    return False


def _score_path(relative_path):
    path = relative_path.lower()
    name = PurePosixPath(relative_path).name.lower()
    suffix = PurePosixPath(relative_path).suffix.lower()

    if suffix not in HIGH_SIGNAL_EXTENSIONS and name not in PRIORITY_FILE_NAMES:
        return None

    score = PRIORITY_FILE_NAMES.get(name, 0)

    if path.startswith("src/"):
        score += 45
    if path.startswith("app/"):
        score += 40
    if path.startswith("lib/"):
        score += 30
    if path.startswith("docs/"):
        score += 25
    if path.startswith("tests/") or "/test" in path:
        score += 15
    if any(token in name for token in ("main", "app", "server", "api", "router", "model", "service")):
        score += 20
    if suffix in {".md", ".rst"}:
        score += 10

    return score


def select_representative_files(tree, limit=MAX_CONTEXT_FILES):
    candidates = []

    for item in tree:
        if item.get("type") != "blob":
            continue

        relative_path = item["path"]
        if _should_skip_path(relative_path):
            continue

        score = _score_path(relative_path)
        if score is None:
            continue

        candidates.append((score, relative_path))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [path for _, path in candidates[:limit]]


def _build_excerpt(content, max_chars=MAX_FILE_EXCERPT_CHARS):
    content = content.strip()
    if len(content) <= max_chars:
        return content

    excerpt = content[:max_chars]
    newline_break = excerpt.rfind("\n")
    if newline_break > max_chars // 2:
        excerpt = excerpt[:newline_break]
    return excerpt.strip()


def _detect_file_role(relative_path):
    path = relative_path.lower()
    name = PurePosixPath(relative_path).name.lower()

    if name.startswith("readme"):
        return "project documentation"
    if path.startswith("docs/"):
        return "supporting documentation"
    if path.startswith("tests/") or "/test" in path:
        return "tests"
    if any(token in name for token in ("main", "app", "server", "index")):
        return "entrypoint or application bootstrap"
    if "route" in name or "controller" in name or "api" in name:
        return "request handling or API surface"
    if "model" in name or "schema" in name:
        return "data model or schema"
    if "service" in name or "client" in name:
        return "service layer or integration"
    return "source file"


def build_code_context(owner, repo):
    tree = fetch_repo_tree(owner, repo)
    selected_files = set(select_representative_files(tree))
    archive_bytes = _download_repo_archive(owner, repo)
    context = []

    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        for file_name in archive.namelist():
            if file_name.endswith("/") or "/" not in file_name:
                continue

            relative_path = file_name.split("/", 1)[1]
            if relative_path not in selected_files:
                continue

            try:
                raw_bytes = archive.read(file_name)
            except KeyError:
                continue

            if len(raw_bytes) > MAX_FILE_BYTES or not _is_probably_text(raw_bytes):
                continue

            content = raw_bytes.decode("utf-8", errors="ignore").strip()
            if not content:
                continue

            context.append(
                {
                    "file": relative_path,
                    "role": _detect_file_role(relative_path),
                    "size_bytes": len(raw_bytes),
                    "excerpt": _build_excerpt(content),
                }
            )

    context.sort(key=lambda item: item["file"])
    return context
