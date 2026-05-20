import re
from collections import Counter
from pathlib import PurePosixPath


def summarize_repo_tree(tree):
    files = [item["path"] for item in tree if item.get("type") == "blob"]
    return {
        "total_files": len(files),
        "sample_files": files[:20],
    }


def _extract_python_symbols(text):
    imports = re.findall(r"^(?:from\s+([A-Za-z0-9_\.]+)\s+import|import\s+([A-Za-z0-9_\.]+))", text, re.MULTILINE)
    functions = re.findall(r"^def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", text, re.MULTILINE)
    classes = re.findall(r"^class\s+([A-Za-z_][A-Za-z0-9_]*)\s*[:\(]", text, re.MULTILINE)

    normalized_imports = []
    for left, right in imports:
        module = left or right
        if module:
            normalized_imports.append(module.split(".")[0])

    return {
        "imports": normalized_imports[:6],
        "functions": functions[:6],
        "classes": classes[:4],
    }


def _extract_js_symbols(text):
    imports = re.findall(
        r"""(?:import\s+.*?\s+from\s+['"]([^'"]+)['"]|require\(['"]([^'"]+)['"]\))""",
        text,
        re.MULTILINE,
    )
    functions = re.findall(
        r"""(?:function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(|const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\(|export\s+function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\()""",
        text,
        re.MULTILINE,
    )

    normalized_imports = []
    for group in imports:
        module = next((item for item in group if item), None)
        if module:
            normalized_imports.append(module)

    normalized_functions = []
    for group in functions:
        function_name = next((item for item in group if item), None)
        if function_name:
            normalized_functions.append(function_name)

    return {
        "imports": normalized_imports[:6],
        "functions": normalized_functions[:6],
        "classes": re.findall(r"class\s+([A-Za-z_][A-Za-z0-9_]*)", text)[:4],
    }


def _extract_markdown_signals(text):
    headings = re.findall(r"^#{1,6}\s+(.+)$", text, re.MULTILINE)
    return {"headings": headings[:6]}


def _infer_file_purpose(path, role, text):
    lowered_path = path.lower()
    lowered_text = text.lower()

    if role == "project documentation":
        return "Describes the project at a high level"
    if role == "supporting documentation":
        return "Documents a subsystem, workflow, or usage area"
    if role == "tests":
        return "Validates application behavior"
    if "route" in lowered_path or "controller" in lowered_path or "api" in lowered_path:
        return "Defines API or request-handling behavior"
    if "model" in lowered_path or "schema" in lowered_path:
        return "Defines data structures or schemas"
    if "service" in lowered_path or "client" in lowered_path:
        return "Implements business logic or external integrations"
    if "config" in lowered_path or "settings" in lowered_path:
        return "Stores application configuration"
    if any(token in lowered_text for token in ("streamlit", "flask", "fastapi", "django", "express")):
        return "Bootstraps an application or web service"
    if any(token in lowered_path for token in ("main", "app", "server", "index")):
        return "Acts as an entrypoint or main application module"
    return "Contains source logic relevant to the repository"


def _categorize_file(path, role):
    lowered_path = path.lower()

    if role in {"project documentation", "supporting documentation", "tests"}:
        return role
    if lowered_path.startswith(("src/", "app/", "lib/")):
        return "core source"
    if any(token in lowered_path for token in ("main", "app", "server", "index", "api", "route", "controller")):
        return "core source"
    return "source file"


def build_file_map(code_context):
    file_map = []

    for entry in code_context:
        path = entry["file"]
        text = entry["excerpt"]
        suffix = PurePosixPath(path).suffix.lower()
        symbols = {"imports": [], "functions": [], "classes": [], "headings": []}

        if suffix == ".py":
            symbols.update(_extract_python_symbols(text))
        elif suffix in {".js", ".jsx", ".ts", ".tsx"}:
            symbols.update(_extract_js_symbols(text))
        elif suffix in {".md", ".rst"}:
            symbols.update(_extract_markdown_signals(text))

        purpose = _infer_file_purpose(path, entry["role"], text)

        file_map.append(
            {
                "file": path,
                "role": entry["role"],
                "category": _categorize_file(path, entry["role"]),
                "purpose": purpose,
                "size_bytes": entry["size_bytes"],
                "imports": symbols.get("imports", [])[:5],
                "functions": symbols.get("functions", [])[:5],
                "classes": symbols.get("classes", [])[:3],
                "headings": symbols.get("headings", [])[:4],
            }
        )

    return file_map


def classify_repo(tree, code_context):
    blob_paths = [item["path"] for item in tree if item.get("type") == "blob"]
    lower_paths = [path.lower() for path in blob_paths]
    extensions = Counter(PurePosixPath(path).suffix.lower() or "[no extension]" for path in blob_paths)
    root_directories = Counter(path.split("/")[0] for path in blob_paths if "/" in path)

    features = []
    if any("dockerfile" in path for path in lower_paths):
        features.append("Docker support")
    if any("test" in path for path in lower_paths):
        features.append("Test suite included")
    if any(path.endswith((".md", ".rst")) for path in lower_paths):
        features.append("Documentation files included")
    if any(".github/workflows/" in path for path in lower_paths):
        features.append("GitHub Actions workflows included")
    if any(path.startswith("docs/") for path in lower_paths):
        features.append("Dedicated docs directory")
    if any(path.startswith(("src/", "app/", "lib/")) for path in lower_paths):
        features.append("Structured source directory")

    file_map = build_file_map(code_context)
    context_roles = Counter(item["role"] for item in code_context)
    file_categories = Counter(item["category"] for item in file_map)

    return {
        "total_repo_files": len(blob_paths),
        "selected_context_files": len(code_context),
        "top_file_extensions": dict(extensions.most_common(10)),
        "top_root_directories": dict(root_directories.most_common(10)),
        "context_roles": dict(context_roles),
        "file_categories": dict(file_categories),
        "features": features,
        "sample_repo_files": blob_paths[:25],
        "sample_context_files": [item["file"] for item in code_context[:15]],
        "file_map": file_map,
    }
