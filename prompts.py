def build_readme_prompt(repo_identity, classified, code_map, supporting_files):
    return f"""
You are an expert technical documentation writer.

Write a grounded, documentation-style README for a GitHub repository.

CRITICAL RULES:
- ONLY use information supported by the inputs below
- Prefer repository metadata and repeated structural signals over one isolated file
- Use the structured code map to infer the main product, architecture, and major subsystems
- Do not confuse docs, tests, or tooling with the core application
- Do NOT invent setup steps, commands, or unsupported features
- Make the README detailed enough to be useful for onboarding and repo understanding
- Keep the whole response under 800 words

Repository Identity:
- Owner: {repo_identity["owner"]}
- Project: {repo_identity["repo"]}
- Description: {repo_identity.get("description", "Not specified in repository")}
- Topics: {repo_identity.get("topics", [])}

Repository Structure Summary:
{classified}

Code Map Input:
{code_map}

Supporting Files Input:
{supporting_files}

OUTPUT FORMAT:

Repository Identity
Owner: ...
Project: ...

Overview
Write 2-4 short paragraphs describing what the repository is, what the main codebase appears to contain,
and how supporting docs/tests/tooling relate to the core project.

Key Features
- List only features or subsystems directly supported by the evidence

Architecture
- Summarize the main modules, layers, or flows visible from the code map

Code Map
For each important file:
- file path
- responsibility
- key functions/classes if visible
- keep each file entry concise

Supporting Files
- Mention important docs, tests, or other non-core files only if they add clarity

Notes
- Mention uncertainty, missing setup details, or scope limits if needed
"""
