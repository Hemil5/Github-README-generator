import os
import re
import time

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

DEFAULT_MODEL = "openai/gpt-oss-120b"
MAX_RETRIES = 4
DEFAULT_RETRY_DELAY = 20


def _get_client():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set. Add it to your environment or .env file.")

    return Groq(api_key=api_key)


def _extract_retry_delay(error):
    message = str(error)
    match = re.search(r"try again in ([0-9]+(?:\.[0-9]+)?)s", message, re.IGNORECASE)
    if match:
        return max(1, int(float(match.group(1)) + 1))
    return DEFAULT_RETRY_DELAY


def generate_text(prompt, model=DEFAULT_MODEL, max_completion_tokens=4096):
    client = _get_client()

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=max_completion_tokens,
            )
            return response.choices[0].message.content
        except Exception as exc:
            error_text = str(exc).lower()
            is_retryable = "429" in error_text or "rate_limit" in error_text

            if not is_retryable or attempt == MAX_RETRIES:
                raise

            time.sleep(_extract_retry_delay(exc))
