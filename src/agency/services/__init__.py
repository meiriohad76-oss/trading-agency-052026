"""Service-layer orchestration helpers for agency runtime flows."""

from .deterministic_rules import (
    DeterministicRuleConfig,
    DeterministicRuleResult,
    evaluate_deterministic_rules,
)
from .deterministic_selection import (
    DeterministicSelectionResult,
    build_deterministic_selection,
)
from .evidence_pack import build_evidence_pack
from .llm_review import (
    LlmReviewProvider,
    LlmReviewResult,
    build_context_only_llm_review,
    build_llm_review_stub,
)
from .selection_persistence import (
    SelectionPayloadWriter,
    build_and_persist_deterministic_selection,
    persist_selection_result,
)
from .signal_adapters import (
    SignalActionabilityConfig,
    build_signal_result,
    build_signal_results_from_scores,
)

__all__ = [
    "DeterministicSelectionResult",
    "DeterministicRuleConfig",
    "DeterministicRuleResult",
    "LlmReviewProvider",
    "LlmReviewResult",
    "SelectionPayloadWriter",
    "SignalActionabilityConfig",
    "build_and_persist_deterministic_selection",
    "build_context_only_llm_review",
    "build_deterministic_selection",
    "build_evidence_pack",
    "build_llm_review_stub",
    "build_signal_result",
    "build_signal_results_from_scores",
    "evaluate_deterministic_rules",
    "persist_selection_result",
]
