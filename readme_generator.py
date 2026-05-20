from llm_generator import generate_text
from models import DEFAULT_README_MODEL
from prompts import build_readme_prompt

FINAL_MAX_TOKENS = 2200
MAX_CODE_MAP_CHARS = 9000
MAX_SUPPORTING_FILES = 8


def _entry_priority(entry):
    path = entry["file"].lower()
    name = path.split("/")[-1]
    category = entry.get("category", "")

    score = 0
    if name.startswith("readme"):
        score += 100
    if category == "core source":
        score += 80
    if path.startswith(("src/", "app/", "lib/")):
        score += 60
    if any(token in name for token in ("main", "app", "server", "index", "api", "model", "service", "route")):
        score += 40
    if path.startswith("docs/"):
        score += 20
    if path.startswith("tests/"):
        score += 10
    return score


def _format_symbols(entry):
    symbols = []
    if entry["classes"]:
        symbols.append(f"Classes: {', '.join(entry['classes'])}")
    if entry["functions"]:
        symbols.append(f"Functions: {', '.join(entry['functions'])}")
    if entry["imports"]:
        symbols.append(f"Imports/Dependencies: {', '.join(entry['imports'])}")
    return symbols


def _build_code_map(file_map):
    core_entries = [
        entry for entry in file_map
        if entry.get("category") in {"core source", "source file"}
    ]
    prioritized_entries = sorted(
        core_entries,
        key=lambda entry: (-_entry_priority(entry), entry["file"]),
    )

    formatted_entries = []
    current_size = 0

    for entry in prioritized_entries:
        lines = [
            f"File: {entry['file']}",
            f"Responsibility: {entry['purpose']}",
        ]
        lines.extend(_format_symbols(entry))

        formatted_entry = "\n".join(lines)
        entry_size = len(formatted_entry) + 2

        if formatted_entries and current_size + entry_size > MAX_CODE_MAP_CHARS:
            break

        formatted_entries.append(formatted_entry)
        current_size += entry_size

    return "\n\n".join(formatted_entries)


def _build_supporting_files(file_map):
    supporting_entries = [
        entry for entry in file_map
        if entry.get("category") in {
            "project documentation",
            "supporting documentation",
            "tests",
        }
    ]
    prioritized_entries = sorted(
        supporting_entries,
        key=lambda entry: (-_entry_priority(entry), entry["file"]),
    )[:MAX_SUPPORTING_FILES]

    return [
        {
            "file": entry["file"],
            "category": entry["category"],
            "purpose": entry["purpose"],
            "headings": entry["headings"][:3],
        }
        for entry in prioritized_entries
    ]


def _compact_classification(classified):
    return {
        "total_repo_files": classified["total_repo_files"],
        "selected_context_files": classified["selected_context_files"],
        "top_file_extensions": classified["top_file_extensions"],
        "top_root_directories": classified["top_root_directories"],
        "context_roles": classified["context_roles"],
        "file_categories": classified["file_categories"],
        "features": classified["features"],
        "sample_repo_files": classified["sample_repo_files"],
    }


def generate_readme(repo_identity, classified, model=DEFAULT_README_MODEL):
    file_map = classified.get("file_map", [])
    if not file_map:
        raise ValueError("No high-signal readable files were found in the repository.")

    prompt = build_readme_prompt(
        repo_identity=repo_identity,
        classified=_compact_classification(classified),
        code_map=_build_code_map(file_map),
        supporting_files=_build_supporting_files(file_map),
    )
    return generate_text(
        prompt,
        model=model,
        max_completion_tokens=FINAL_MAX_TOKENS,
    )
