"""
Intelligent Conversational Engine for Project Go 81.
Stage 5 Architecture:
- Context awareness & multi-turn session tracking
- Deterministic arithmetic calculator
- Timezone-aware system time grounding
- Factual verification & hallucination prevention (Movies, Sports, Cutting-edge information)
- Bounded local Ollama inference without cloud fallback
- Intent classification and natural conversational routing
"""

from .timezone import get_current_time, format_local_timestamp, to_utc_iso, get_system_time_context
from .calculator import SafeCalculator, evaluate_math_expression, is_arithmetic_query
from .intent import IntentCategory, IntentResult, IntentClassifier
from .session_manager import ConversationSessionManager, SessionTurn, get_session_manager
from .knowledge_guard import KnowledgeGuard
from .engine import IntelligentConversationalEngine, get_conversational_engine

__all__ = [
    "get_current_time",
    "format_local_timestamp",
    "to_utc_iso",
    "get_system_time_context",
    "SafeCalculator",
    "evaluate_math_expression",
    "is_arithmetic_query",
    "IntentCategory",
    "IntentResult",
    "IntentClassifier",
    "ConversationSessionManager",
    "SessionTurn",
    "get_session_manager",
    "KnowledgeGuard",
    "IntelligentConversationalEngine",
    "get_conversational_engine",
]
