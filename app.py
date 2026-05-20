import streamlit as st

# comment

from github_fetcher import build_code_context, fetch_repo_metadata, fetch_repo_tree
from models import (
    CHAT_MODEL_OPTIONS,
    DEFAULT_CHAT_MODEL,
    DEFAULT_README_MODEL,
    README_MODEL_OPTIONS,
)
from readme_generator import generate_readme
from repo_chat import answer_repo_question
from repo_parser import classify_repo
from utils import parse_url

README_MODEL_IDS = [item["id"] for item in README_MODEL_OPTIONS]
CHAT_MODEL_IDS = [item["id"] for item in CHAT_MODEL_OPTIONS]


def _init_state():
    defaults = {
        "repo_cache": {},
        "chat_history": {},
        "repo_locked": False,
        "repo_ready": False,
        "processing_repo": False,
        "active_cache_key": "",
        "repo_error": "",
        "repo_url_input": "",
        "readme_model": DEFAULT_README_MODEL,
        "chat_model": DEFAULT_CHAT_MODEL,
        "last_repo_url": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _reset_app():
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def _lock_repo_input():
    if st.session_state.repo_url_input.strip():
        st.session_state.repo_locked = True
        st.session_state.repo_ready = False
        st.session_state.repo_error = ""
        st.session_state.last_repo_url = st.session_state.repo_url_input.strip()


def _on_readme_model_change():
    if st.session_state.repo_ready or st.session_state.repo_locked:
        st.session_state.repo_locked = False
        st.session_state.repo_ready = False
        st.session_state.active_cache_key = ""
        st.session_state.repo_error = ""
        if st.session_state.last_repo_url:
            st.session_state.repo_url_input = st.session_state.last_repo_url


_init_state()

st.title("GitHub README Generator")

top_left, top_right = st.columns([1, 1])
with top_left:
    selected_readme_model = st.selectbox(
        "README model",
        README_MODEL_IDS,
        index=README_MODEL_IDS.index(st.session_state.readme_model),
        key="readme_model",
        disabled=st.session_state.processing_repo,
        on_change=_on_readme_model_change,
        format_func=lambda model_id: next(
            item["label"] for item in README_MODEL_OPTIONS if item["id"] == model_id
        ),
    )
with top_right:
    selected_chat_model = st.selectbox(
        "Chat model",
        CHAT_MODEL_IDS,
        index=CHAT_MODEL_IDS.index(st.session_state.chat_model),
        key="chat_model",
        disabled=st.session_state.processing_repo,
        format_func=lambda model_id: next(
            item["label"] for item in CHAT_MODEL_OPTIONS if item["id"] == model_id
        ),
    )

if st.button("Refresh"):
    _reset_app()
    st.rerun()

repo_url = st.text_input(
    "Paste GitHub repo URL:",
    key="repo_url_input",
    disabled=st.session_state.repo_locked,
    on_change=_lock_repo_input,
)

if st.session_state.repo_error:
    st.error(st.session_state.repo_error)

if repo_url and st.session_state.repo_locked and not st.session_state.repo_ready:
    try:
        owner, repo = parse_url(repo_url)
        cache_key = f"{owner}/{repo}::{selected_readme_model}"
        st.session_state.processing_repo = True

        if cache_key not in st.session_state.repo_cache:
            with st.spinner("Analyzing repository structure and generating README..."):
                repo_identity = fetch_repo_metadata(owner, repo)
                repo_tree = fetch_repo_tree(owner, repo)
                code_context = build_code_context(owner, repo)
                classified = classify_repo(repo_tree, code_context)
                readme = generate_readme(repo_identity, classified, model=selected_readme_model)

            st.session_state.repo_cache[cache_key] = {
                "repo_identity": repo_identity,
                "code_context": code_context,
                "classified": classified,
                "readme": readme,
                "readme_model": selected_readme_model,
            }
            st.session_state.chat_history[cache_key] = []

        st.session_state.active_cache_key = cache_key
        st.session_state.repo_ready = True
        st.session_state.repo_error = ""
    except Exception as exc:
        message = str(exc)
        st.session_state.repo_locked = False
        st.session_state.repo_ready = False
        st.session_state.active_cache_key = ""

        if "429" in message or "rate limit" in message.lower():
            st.session_state.repo_error = (
                "Groq rate limit reached while processing the repository. "
                "Please wait a bit and try again."
            )
        else:
            st.session_state.repo_error = "Please paste a valid public GitHub repository URL."
    finally:
        st.session_state.processing_repo = False
        st.rerun()

if st.session_state.repo_ready and st.session_state.active_cache_key:
    repo_data = st.session_state.repo_cache[st.session_state.active_cache_key]
    repo_identity = repo_data["repo_identity"]
    code_context = repo_data["code_context"]
    classified = repo_data["classified"]
    readme = repo_data["readme"]

    st.info(
        f"Scanned {classified['total_repo_files']} repo files and selected "
        f"{classified['selected_context_files']} representative files."
    )
    st.caption(f"README model used: {repo_data['readme_model']} | Chat model: {selected_chat_model}")

    st.subheader("Generated README.md")
    st.markdown(readme)
    st.download_button(
        label="Download README.md",
        data=readme,
        file_name="README.md",
        mime="text/markdown",
    )

    st.subheader("Ask About This Repository")
    for message in st.session_state.chat_history.get(st.session_state.active_cache_key, []):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    user_question = st.chat_input(
        "Ask about files, functions, architecture, or where something is implemented",
        disabled=not st.session_state.repo_ready or st.session_state.processing_repo,
    )
    if user_question:
        st.session_state.chat_history[st.session_state.active_cache_key].append(
            {"role": "user", "content": user_question}
        )
        with st.chat_message("user"):
            st.markdown(user_question)

        with st.chat_message("assistant"):
            with st.spinner("Answering from the repository map..."):
                answer = answer_repo_question(
                    repo_identity=repo_identity,
                    classified=classified,
                    code_context=code_context,
                    readme=readme,
                    question=user_question,
                    model=selected_chat_model,
                )
                st.markdown(answer)

        st.session_state.chat_history[st.session_state.active_cache_key].append(
            {"role": "assistant", "content": answer}
        )
