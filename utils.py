# utils.py or at top of your main file
from urllib.parse import urlparse

def parse_url(url):
    """
    Given a GitHub URL like https://github.com/owner/repo,
    return owner and repo as tuple.
    """
    path_parts = urlparse(url).path.strip("/").split("/")
    if len(path_parts) >= 2:
        owner, repo = path_parts[0], path_parts[1]
        # remove .git if user copied clone URL by mistake
        repo = repo.replace(".git", "")
        return owner, repo
    else:
        raise ValueError("Invalid GitHub URL")