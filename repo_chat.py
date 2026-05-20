import re
from difflib import SequenceMatcher

from github_fetcher import fetch_file_content
from llm_generator import generate_text
from models import DEFAULT_CHAT_MODEL

CHAT_MAX_TOKENS = 1000
MAX_CHAT_CONTEXT_CHARS = 7000
MAX_LIVE_FILE_CHARS = 3500


def _tokenize(text):
    return set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_./-]*", text.lower()))


def _extract_code_blocks(text):
    fenced_blocks = re.findall(r"```(?:[\w+-]*)\n(.*?)```", text, re.DOTALL)
    if fenced_blocks:
        return [block.strip() for block in fenced_blocks if block.strip()]
    return []


def _looks_like_code(text):
    if _extract_code_blocks(text):
        return True

    code_markers = [
        "def ", "class ", "import ", "from ", "return ", "const ", "function ",
        "=>", "{", "}", "if (", "elif ", "while ", "for ", "try:", "except ",
    ]
    lowered = text.lower()
    return sum(1 for marker in code_markers if marker in lowered) >= 2


def _entry_search_text(entry):
    fields = [
        entry.get("file", ""),
        entry.get("role", ""),
        entry.get("category", ""),
        entry.get("purpose", ""),
        " ".join(entry.get("functions", [])),
        " ".join(entry.get("classes", [])),
        " ".join(entry.get("imports", [])),
        " ".join(entry.get("headings", [])),
    ]
    return " ".join(fields).lower()


def _score_file_map_entry(entry, query_tokens):
    search_text = _entry_search_text(entry)
    score = 0

    for token in query_tokens:
        if token in search_text:
            score += 2
        if token == entry.get("file", "").lower():
            score += 6

    file_name = entry.get("file", "").split("/")[-1].lower()
    if file_name in query_tokens:
        score += 8

    return score


def _snippet_similarity(snippet, text):
    snippet = snippet.strip().lower()
    text = text.strip().lower()
    if not snippet or not text:
        return 0.0

    if snippet in text:
        return 1.0

    snippet_lines = [line.strip() for line in snippet.splitlines() if line.strip()]
    text_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not snippet_lines or not text_lines:
        return SequenceMatcher(None, snippet[:500], text[:500]).ratio()

    overlap = 0
    for line in snippet_lines[:12]:
        if len(line) >= 8 and any(line in text_line for text_line in text_lines):
            overlap += 1

    overlap_score = overlap / max(min(len(snippet_lines), 12), 1)
    ratio_score = SequenceMatcher(None, snippet[:800], text[:1600]).ratio()
    return max(overlap_score, ratio_score)


def _select_relevant_entries(classified, question, limit=6):
    query_tokens = _tokenize(question)
    file_map = classified.get("file_map", [])
    scored_entries = []

    for entry in file_map:
        score = _score_file_map_entry(entry, query_tokens)
        if score > 0:
            scored_entries.append((score, entry))

    scored_entries.sort(key=lambda item: (-item[0], item[1]["file"]))
    relevant_entries = [entry for _, entry in scored_entries[:limit]]

    if relevant_entries:
        return relevant_entries

    core_entries = [
        entry for entry in file_map
        if entry.get("category") in {"core source", "source file"}
    ]
    return core_entries[:limit]


def _match_snippet_to_entries(classified, code_context, question, limit=4):
    snippet_blocks = _extract_code_blocks(question)
    snippet = "\n\n".join(snippet_blocks).strip() if snippet_blocks else question.strip()
    if not snippet:
        return [], 0.0

    scored_entries = []
    excerpt_lookup = {entry["file"]: entry for entry in code_context}
    for entry in classified.get("file_map", []):
        excerpt_entry = excerpt_lookup.get(entry["file"])
        excerpt = excerpt_entry.get("excerpt", "") if excerpt_entry else ""
        haystack = "\n".join(
            [
                entry.get("purpose", ""),
                " ".join(entry.get("functions", [])),
                " ".join(entry.get("classes", [])),
                excerpt,
            ]
        )
        similarity = _snippet_similarity(snippet, haystack)
        if similarity > 0.15:
            scored_entries.append((similarity, entry))

    scored_entries.sort(key=lambda item: (-item[0], item[1]["file"]))
    matched_entries = [entry for _, entry in scored_entries[:limit]]
    top_score = scored_entries[0][0] if scored_entries else 0.0
    return matched_entries, top_score


def _select_relevant_context(code_context, relevant_files, question, limit=4):
    relevant_paths = {entry["file"] for entry in relevant_files}
    matching_context = [
        entry for entry in code_context
        if entry["file"] in relevant_paths
    ]

    if matching_context:
        return matching_context[:limit]

    query_tokens = _tokenize(question)
    scored_context = []
    for entry in code_context:
        haystack = f"{entry['file']} {entry.get('excerpt', '')}".lower()
        score = sum(1 for token in query_tokens if token in haystack)
        if score > 0:
            scored_context.append((score, entry))

    scored_context.sort(key=lambda item: (-item[0], item[1]["file"]))
    return [entry for _, entry in scored_context[:limit]]


def _fetch_live_context(repo_identity, candidate_entries, question):
    live_blocks = []
    if not candidate_entries:
        return ""

    owner = repo_identity["owner"]
    repo = repo_identity["repo"]
    snippet_blocks = _extract_code_blocks(question)
    snippet = "\n\n".join(snippet_blocks).strip() if snippet_blocks else question.strip()

    for entry in candidate_entries[:2]:
        content = fetch_file_content(owner, repo, entry["file"])
        if not content:
            continue

        excerpt = content[:MAX_LIVE_FILE_CHARS]
        if snippet:
            similarity = _snippet_similarity(snippet, content)
        else:
            similarity = 0.0

        live_blocks.append(
            "\n".join(
                [
                    f"Live File: {entry['file']}",
                    f"Similarity: {similarity:.2f}",
                    "Content:",
                    excerpt,
                ]
            )
        )

    return "\n\n".join(live_blocks)


def _format_file_map_entries(entries):
    blocks = []
    for entry in entries:
        lines = [
            f"File: {entry['file']}",
            f"Role: {entry['role']}",
            f"Category: {entry['category']}",
            f"Purpose: {entry['purpose']}",
        ]
        if entry["classes"]:
            lines.append(f"Classes: {', '.join(entry['classes'])}")
        if entry["functions"]:
            lines.append(f"Functions: {', '.join(entry['functions'])}")
        if entry["imports"]:
            lines.append(f"Imports/Dependencies: {', '.join(entry['imports'])}")
        if entry["headings"]:
            lines.append(f"Headings: {', '.join(entry['headings'])}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _format_code_context(entries):
    blocks = []
    current_size = 0

    for entry in entries:
        block = "\n".join(
            [
                f"File: {entry['file']}",
                "Excerpt:",
                entry["excerpt"],
            ]
        )
        block_size = len(block) + 2

        if blocks and current_size + block_size > MAX_CHAT_CONTEXT_CHARS:
            break

        blocks.append(block)
        current_size += block_size

    return "\n\n".join(blocks)


def _question_mode(question):
    if _looks_like_code(question):
        return "snippet"
    return "repo"


def answer_repo_question(repo_identity, classified, code_context, readme, question, model=DEFAULT_CHAT_MODEL):
    mode = _question_mode(question)

    if mode == "snippet":
        relevant_entries, confidence = _match_snippet_to_entries(classified, code_context, question)
    else:
        relevant_entries = _select_relevant_entries(classified, question)
        confidence = 1.0 if relevant_entries else 0.0

    relevant_context = _select_relevant_context(code_context, relevant_entries, question)
    live_context = ""
    if mode == "snippet" or confidence < 0.45:
        live_context = _fetch_live_context(repo_identity, relevant_entries, question)

    prompt = f"""
You are a repo-aware documentation assistant. Answer the user's question using only the repository evidence below.

Rules:
- Stay grounded in the provided repository data
- If something is uncertain, say so clearly
- Prefer citing file names and visible functions/classes
- If this is a pasted code snippet question, explain what the snippet appears to do, where it likely belongs, and what nearby code or file it connects to
- Keep the answer concise but useful

Question Mode:
{mode}

Repository:
- Owner: {repo_identity["owner"]}
- Project: {repo_identity["repo"]}
- Description: {repo_identity.get("description", "Not specified in repository")}

Generated README:
{readme}

Repository Summary:
{{
  "total_repo_files": {classified.get("total_repo_files")},
  "selected_context_files": {classified.get("selected_context_files")},
  "features": {classified.get("features", [])},
  "top_root_directories": {classified.get("top_root_directories", {})}
}}

Relevant File Map Entries:
{_format_file_map_entries(relevant_entries)}

Relevant Cached File Excerpts:
{_format_code_context(relevant_context)}

Live Fallback File Content:
{live_context if live_context else "Not needed"}

User Question:
{question}

Answer format:
- Direct answer first
- If relevant, mention the most likely file or files
- Then a short "Evidence:" line mentioning the most relevant files
"""

    return generate_text(
        prompt,
        model=model,
        max_completion_tokens=CHAT_MAX_TOKENS,
    )
