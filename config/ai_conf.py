"""
AI / Agent 配置层（模型供应商可插拔）。

所有主流提供方都兼容 OpenAI 协议，这里统一用 openai SDK，靠 .env 切换：
  - 本地 Ollama（默认）：LLM_BASE_URL=http://localhost:11434/v1
  - 通义千问 DashScope ：LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
  - DeepSeek           ：LLM_BASE_URL=https://api.deepseek.com
业务代码只认 get_llm_client() / get_embedding_client()，换模型零改动。
"""
import os
from dataclasses import dataclass, field

from config.env_loader import load_project_env

load_project_env()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _csv(name: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, "").split(",") if item.strip())


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _first_env(names: tuple[str, ...], default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return default


def normalize_rag_ranking(value: str | None) -> str:
    ranking = (value or "hybrid").strip().lower()
    if not ranking:
        return "hybrid"
    if ranking not in {"vector", "hybrid"}:
        raise ValueError("RAG_RANKING must be either 'hybrid' or 'vector'")
    return ranking


def normalize_rag_search_version(value: str | None) -> str:
    version = (value or "v1").strip().lower()
    if not version:
        return "v1"
    if version not in {"v1", "v2"}:
        raise ValueError("RAG_SEARCH_VERSION must be either 'v1' or 'v2'")
    return version


def normalize_rag_chunk_type_filter(value: str | None) -> str | None:
    chunk_type = (value or "").strip().lower()
    if not chunk_type:
        return None
    if chunk_type not in {"summary", "body"}:
        raise ValueError("RAG_CHUNK_TYPE_FILTER must be empty, 'summary', or 'body'")
    return chunk_type


def normalize_b_v3_source_policy(value: str | None) -> str:
    policy = (value or "local_test").strip().lower()
    if not policy:
        return "local_test"
    if policy not in {"local_test", "review_safe", "strict"}:
        raise ValueError("B_V3_SOURCE_POLICY must be 'local_test', 'review_safe', or 'strict'")
    return policy


@dataclass(frozen=True)
class AISettings:
    app_env: str = os.getenv("APP_ENV", os.getenv("ENV", "development")).strip().lower()

    # 主力对话模型（OpenAI 兼容）
    llm_base_url: str = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
    llm_api_key: str = field(default_factory=lambda: _first_env(("LLM_API_KEY", "SILICONFLOW_API_KEY"), "ollama"))
    llm_model: str = os.getenv("LLM_MODEL", "gpt-oss:20b")
    llm_reasoning_effort: str = os.getenv("LLM_REASONING_EFFORT", "").strip()
    llm_thinking_enabled: bool = _bool("LLM_THINKING_ENABLED", False)
    llm_timeout_seconds: int = _int("LLM_TIMEOUT_SECONDS", 90)

    # Embedding（Phase 4 RAG）
    embedding_base_url: str = os.getenv("EMBEDDING_BASE_URL", "http://localhost:11434/v1")
    embedding_api_key: str = field(default_factory=lambda: _first_env(("EMBEDDING_API_KEY", "SILICONFLOW_API_KEY"), "ollama"))
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "qwen3-embedding:4b")

    # RAG defaults are summary-first; body fallback is enabled by Query Router only.
    rag_query_router_enabled: bool = _bool("RAG_QUERY_ROUTER_ENABLED", True)
    rag_search_version: str = normalize_rag_search_version(os.getenv("RAG_SEARCH_VERSION", "v1"))
    rag_ranking: str = normalize_rag_ranking(os.getenv("RAG_RANKING", "hybrid"))
    rag_recall_limit: int = _int("RAG_RECALL_LIMIT", 50)
    rag_chunk_type_filter: str | None = normalize_rag_chunk_type_filter(os.getenv("RAG_CHUNK_TYPE_FILTER", "summary"))
    rag_expand_body_evidence: bool = _bool("RAG_EXPAND_BODY_EVIDENCE", True)
    rag_body_chunks_per_parent: int = _int("RAG_BODY_CHUNKS_PER_PARENT", 1)
    rag_body_fallback_slots: int = _int("RAG_BODY_FALLBACK_SLOTS", 0)
    rag_econ_collection_enabled: bool = _bool("RAG_ECON_COLLECTION_ENABLED", False)
    rag_econ_collection_name: str = os.getenv("RAG_ECON_COLLECTION_NAME", "toutiao_exp_econ_recent_20260621")
    reranker_model: str = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")

    # Answer Contract / Validator gray rollout. Defaults: global shadow, econ route enforce.
    answer_contract_enabled: bool = _bool("ANSWER_CONTRACT_ENABLED", True)
    answer_contract_default_style: str = os.getenv("ANSWER_CONTRACT_DEFAULT_STYLE", "plain_language")
    answer_contract_default_detail: str = os.getenv("ANSWER_CONTRACT_DEFAULT_DETAIL", "brief")
    answer_contract_default_max_points: int = _int("ANSWER_CONTRACT_DEFAULT_MAX_POINTS", 3)
    answer_contract_require_citations_for_news: bool = _bool("ANSWER_CONTRACT_REQUIRE_CITATIONS_FOR_NEWS", True)
    answer_contract_require_evidence_for_news: bool = _bool("ANSWER_CONTRACT_REQUIRE_EVIDENCE_FOR_NEWS", True)
    answer_contract_allow_background: bool = _bool("ANSWER_CONTRACT_ALLOW_BACKGROUND", True)
    answer_contract_background_policy: str = os.getenv(
        "ANSWER_CONTRACT_BACKGROUND_POLICY", "one_sentence_plain_explanation"
    )

    answer_validation_enabled: bool = _bool("ANSWER_VALIDATION_ENABLED", True)
    answer_validation_mode: str = os.getenv("ANSWER_VALIDATION_MODE", "shadow")
    answer_validation_enforce_routes: tuple[str, ...] = _csv("ANSWER_VALIDATION_ENFORCE_ROUTES") or (
        "econ_finance_query",
    )
    answer_validation_hallucination_label: str = os.getenv(
        "ANSWER_VALIDATION_HALLUCINATION_LABEL", "hallucination_risk"
    )
    answer_rewrite_on_fail: bool = _bool("ANSWER_REWRITE_ON_FAIL", True)
    answer_max_rewrite_attempts: int = _int("ANSWER_MAX_REWRITE_ATTEMPTS", 1)
    answer_thinking_event_enabled: bool = _bool("ANSWER_THINKING_EVENT_ENABLED", False)
    answer_validation_done_field_enabled: bool = _bool("ANSWER_VALIDATION_DONE_FIELD_ENABLED", True)
    answer_validation_done_detail_level: str = os.getenv("ANSWER_VALIDATION_DONE_DETAIL_LEVEL", "summary")
    answer_validation_log_diagnostics: bool = _bool("ANSWER_VALIDATION_LOG_DIAGNOSTICS", True)
    answer_validation_store_metadata: bool = _bool("ANSWER_VALIDATION_STORE_METADATA", True)
    answer_validation_expose_internal_details: bool = _bool("ANSWER_VALIDATION_EXPOSE_INTERNAL_DETAILS", False)
    answer_no_evidence_policy: str = os.getenv("ANSWER_NO_EVIDENCE_POLICY", "refuse_with_suggestion")
    answer_low_confidence_evidence_policy: str = os.getenv(
        "ANSWER_LOW_CONFIDENCE_EVIDENCE_POLICY", "refuse_if_not_supported"
    )

    # B-v3 source policy controls whether low-trust external/OCR leads can become visible candidates.
    b_v3_source_policy: str = normalize_b_v3_source_policy(os.getenv("B_V3_SOURCE_POLICY", "local_test"))

    # Context Manager / Memory v1. Memory is never treated as factual news evidence.
    context_manager_enabled: bool = _bool("CONTEXT_MANAGER_ENABLED", True)
    session_summary_enabled: bool = _bool("SESSION_SUMMARY_ENABLED", True)
    long_term_memory_enabled: bool = _bool("LONG_TERM_MEMORY_ENABLED", False)
    context_recent_turns: int = _int("CONTEXT_RECENT_TURNS", 6)
    context_summary_message_threshold: int = _int("CONTEXT_SUMMARY_MESSAGE_THRESHOLD", 12)
    context_summary_char_threshold: int = _int("CONTEXT_SUMMARY_CHAR_THRESHOLD", 6000)
    context_max_recent_evidence_ids: int = _int("CONTEXT_MAX_RECENT_EVIDENCE_IDS", 8)

    # Harness 硬限额（MVP 护栏）
    max_tool_calls_per_turn: int = _int("MAX_TOOL_CALLS_PER_TURN", 5)
    max_web_calls_per_session: int = _int("MAX_WEB_CALLS_PER_SESSION", 3)
    max_fetch_bytes: int = _int("MAX_FETCH_BYTES", 1024 * 1024)
    tool_timeout_seconds: int = _int("TOOL_TIMEOUT_SECONDS", 30)
    max_redirects: int = _int("MAX_REDIRECTS", 3)
    max_chunks_per_answer: int = _int("MAX_CHUNKS_PER_ANSWER", 8)

    # 联网搜索
    web_search_api_key: str = os.getenv("WEB_SEARCH_API_KEY", "")
    # 聚合数据新闻 API（每天 50 次配额）
    juhe_api_key: str = os.getenv("JUHE_API_KEY", "")
    web_allowed_domains: tuple[str, ...] = _csv("WEB_ALLOWED_DOMAINS")
    web_blocked_domains: tuple[str, ...] = _csv("WEB_BLOCKED_DOMAINS")
    web_capture_output_dir: str = os.getenv("WEB_CAPTURE_OUTPUT_DIR", "work/web_captures")
    web_capture_viewport_width: int = _int("WEB_CAPTURE_VIEWPORT_WIDTH", 1280)
    web_capture_viewport_height: int = _int("WEB_CAPTURE_VIEWPORT_HEIGHT", 1600)
    web_capture_render_max_chars: int = _int("WEB_CAPTURE_RENDER_MAX_CHARS", 50000)
    ocr_provider_name: str = os.getenv("OCR_PROVIDER", "paddleocr")
    ocr_min_confidence: float = _float("OCR_MIN_CONFIDENCE", 0.35)
    ocr_clean_max_chars: int = _int("OCR_CLEAN_MAX_CHARS", 20000)
    ocr_min_clean_chars: int = _int("OCR_MIN_CLEAN_CHARS", 8)

    @property
    def web_allowed_domains_list(self) -> list[str]:
        return list(self.web_allowed_domains)

    @property
    def web_blocked_domains_list(self) -> list[str]:
        return list(self.web_blocked_domains)


settings = AISettings()


def get_llm_client():
    """主力对话模型客户端（OpenAI 兼容）。"""
    from openai import AsyncOpenAI

    return AsyncOpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key or "not-needed")


def get_embedding_client():
    """Embedding 客户端（Phase 4 RAG 用）。"""
    from openai import AsyncOpenAI

    return AsyncOpenAI(base_url=settings.embedding_base_url, api_key=settings.embedding_api_key or "not-needed")
