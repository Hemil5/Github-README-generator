from github_fetcher import build_code_context, fetch_repo_metadata, fetch_repo_tree
from readme_generator import generate_readme
from repo_parser import classify_repo
from utils import parse_url


def main():
    print("Using model: openai/gpt-oss-120b")
    repo_url = input("Enter GitHub repository URL: ").strip()
    owner, repo = parse_url(repo_url)

    repo_identity = fetch_repo_metadata(owner, repo)
    repo_tree = fetch_repo_tree(owner, repo)
    code_context = build_code_context(owner, repo)
    classified = classify_repo(repo_tree, code_context)
    print(
        f"Scanned {classified['total_repo_files']} repo files and selected "
        f"{classified['selected_context_files']} representative files."
    )
    readme = generate_readme(repo_identity, classified)

    with open("GENERATED_README.md", "w", encoding="utf-8") as file:
        file.write(readme)

    print("README generated as GENERATED_README.md")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}")
