"""Anthropic SDK client with streaming and retry."""
import time
import anthropic
from config import ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_MAX_TOKENS

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not ANTHROPIC_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY 未設定。請在 .env 檔案中加入你的 API key。"
            )
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def analyze_stocks(
    system_prompt: str,
    user_prompt: str,
    on_token=None,
    max_retries: int = 3,
) -> str:
    """
    Call Claude with streaming.
    on_token: optional callback(text_chunk) called for each streamed token.
    Returns full response text.
    """
    client = _get_client()

    for attempt in range(max_retries):
        try:
            chunks = []
            with client.messages.stream(
                model=CLAUDE_MODEL,
                max_tokens=CLAUDE_MAX_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            ) as stream:
                for text in stream.text_stream:
                    chunks.append(text)
                    if on_token:
                        on_token(text)
            return "".join(chunks)

        except anthropic.APIStatusError as e:
            if e.status_code == 529 and attempt < max_retries - 1:
                wait = 30 * (attempt + 1)
                if on_token:
                    on_token(f"\n[API 過載，{wait}秒後重試...]\n")
                time.sleep(wait)
                continue
            raise
        except anthropic.APIConnectionError:
            if attempt < max_retries - 1:
                time.sleep(10)
                continue
            raise

    raise RuntimeError("Claude API 重試次數已達上限")
