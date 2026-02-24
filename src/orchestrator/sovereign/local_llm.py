"""
Sovereign / air-gapped module.

Drop-in replacement for ChatAnthropic that uses a locally-running Ollama instance.
Enables deployment in sensitive industries (defence, pharma) without cloud LLM calls.

Usage — set in .env:
    SOVEREIGN_MODE=true
    OLLAMA_BASE_URL=http://localhost:11434
    OLLAMA_MODEL=llama3:70b    # or mistral:7b for faster/lighter

The agent nodes check settings.sovereign_mode and call get_llm() which switches
between ChatAnthropic and ChatOllama transparently.

To run Ollama locally:
    curl -fsSL https://ollama.ai/install.sh | sh
    ollama pull llama3:70b
"""

from orchestrator.config import settings


def get_local_llm():
    """Return a ChatOllama instance configured from settings."""
    try:
        from langchain_community.chat_models import ChatOllama

        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=0,
            num_ctx=8192,
        )
    except ImportError as exc:
        raise RuntimeError(
            "langchain-community not installed. Run: pip install langchain-community"
        ) from exc


def get_llm():
    """
    Factory: returns the appropriate LLM based on sovereign_mode setting.
    Call this in agent nodes instead of importing ChatAnthropic directly.
    """
    if settings.sovereign_mode:
        return get_local_llm()

    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(
        model="claude-sonnet-4-6",
        api_key=settings.anthropic_api_key,
        temperature=0,
        max_tokens=1024,
    )
