import logging
import re

from app import database

logger = logging.getLogger(__name__)

# Quantization suffixes to strip from Ollama model names
_QUANT_PATTERN = re.compile(r"-(?:q\d[\w_]*|fp16|fp32|f16|f32|gguf|ggml)$", re.IGNORECASE)

# Common size patterns like "8b", "70b", "1.5b", "8x7b"
_SIZE_PATTERN = re.compile(r"(\d+(?:\.\d+)?x?\d*b)", re.IGNORECASE)

# Known vendor prefixes on OpenRouter
_VENDOR_MAP = {
    "llama": "meta-llama",
    "codellama": "meta-llama",
    "mistral": "mistralai",
    "mixtral": "mistralai",
    "gemma": "google",
    "phi": "microsoft",
    "qwen": "qwen",
    "deepseek": "deepseek",
    "command": "cohere",
    "claude": "anthropic",
    "gpt": "openai",
    "starcoder": "bigcode",
    "wizardlm": "microsoft",
    "yi": "01-ai",
    "solar": "upstage",
    "nous": "nousresearch",
    "hermes": "nousresearch",
    "dolphin": "cognitivecomputations",
    "openchat": "openchat",
    "neural": "intel",
    "orca": "microsoft",
    "zephyr": "huggingfaceh4",
    "vicuna": "lmsys",
}


def _normalize_ollama_name(name: str) -> tuple[str, list[str]]:
    """Normalize an Ollama model name into a base name and keyword tokens.

    Returns (base_name, tokens) where tokens are useful for matching.
    Example: "llama3:8b-instruct-q4_0" -> ("llama3", ["llama", "3", "8b", "instruct"])
    """
    # Split on colon: base:tag
    parts = name.split(":", 1)
    base = parts[0].lower().strip()
    tag = parts[1].lower().strip() if len(parts) > 1 else ""

    # Remove "latest" tag
    if tag == "latest":
        tag = ""

    # Strip quantization from tag
    tag = _QUANT_PATTERN.sub("", tag)

    # Combine base and tag for tokenization
    full = f"{base}-{tag}" if tag else base

    # Tokenize: split on hyphens, underscores, dots, and number boundaries
    raw_tokens = re.split(r"[-_./]", full)
    tokens: list[str] = []
    for t in raw_tokens:
        # Further split on letter/number boundaries: "llama3" -> ["llama", "3"]
        sub = re.findall(r"[a-z]+|\d+(?:\.\d+)?(?:x\d+)?b?", t)
        tokens.extend(sub)

    # Remove empty and very short noise tokens
    tokens = [t for t in tokens if len(t) >= 1]

    return base, tokens


def _score_match(ollama_tokens: list[str], ollama_base: str, openrouter_id: str) -> float:
    """Score how well an OpenRouter model ID matches the Ollama tokens."""
    or_lower = openrouter_id.lower()
    or_parts = or_lower.replace("/", "-").replace("_", "-").replace(".", "-")
    or_tokens = set(re.split(r"[-]", or_parts))

    score = 0.0

    # Check base name presence (highest weight)
    # Strip digits from base for family matching: "llama3" -> "llama"
    base_family = re.sub(r"\d+$", "", ollama_base)
    if base_family and base_family in or_lower:
        score += 10.0

    # Check vendor prefix
    for key, vendor in _VENDOR_MAP.items():
        if ollama_base.startswith(key) and or_lower.startswith(vendor):
            score += 5.0
            break

    # Token overlap
    ollama_set = set(ollama_tokens)
    overlap = ollama_set & or_tokens
    score += len(overlap) * 2.0

    # Size match bonus
    ollama_sizes = [t for t in ollama_tokens if _SIZE_PATTERN.match(t)]
    or_sizes = [t for t in or_tokens if _SIZE_PATTERN.match(t)]
    if ollama_sizes and or_sizes:
        if set(ollama_sizes) & set(or_sizes):
            score += 5.0
        else:
            score -= 3.0  # Size mismatch penalty

    # Variant match (instruct, chat, etc.)
    variants = {"instruct", "chat", "code", "coder", "vision", "math"}
    ollama_variants = ollama_set & variants
    or_variants = or_tokens & variants
    if ollama_variants and ollama_variants == or_variants:
        score += 3.0
    elif ollama_variants and not ollama_variants & or_variants:
        score -= 2.0

    # Prefer shorter IDs (less specific = more likely the base model)
    score -= len(openrouter_id) * 0.01

    return score


async def resolve_openrouter_id(ollama_model: str) -> str | None:
    """Resolve an Ollama model name to an OpenRouter model ID.

    Resolution order: user overrides -> cached auto-matches -> heuristic matching.
    """
    # Check existing mapping
    mapping = await database.get_mapping(ollama_model)
    if mapping:
        return mapping["openrouter_id"]

    # Run heuristic matching
    all_prices = await database.get_all_prices()
    if not all_prices:
        return None

    openrouter_ids = [p["openrouter_id"] for p in all_prices]
    base, tokens = _normalize_ollama_name(ollama_model)

    best_id = None
    best_score = 0.0

    for or_id in openrouter_ids:
        s = _score_match(tokens, base, or_id)
        if s > best_score:
            best_score = s
            best_id = or_id

    # Require a minimum confidence threshold
    if best_score < 12.0 or best_id is None:
        logger.debug("No confident match for '%s' (best score=%.1f)", ollama_model, best_score)
        return None

    # Cache the auto-match
    await database.upsert_mapping(ollama_model, best_id, is_user_override=False)
    logger.info("Auto-matched '%s' -> '%s' (score=%.1f)", ollama_model, best_id, best_score)
    return best_id
