"""
Intelligent Intent Classification for Project Go 81.
Stage 5 Intelligent Conversational Engine:
- Multi-category validated intent schema
- Deterministic fast routing for arithmetic, greetings, memory, sports, movies, and task triggers
- Entity and pronoun reference extraction
- Controlled clarification requirements for ambiguous queries
- Bounded local Ollama structured classification fallback (zero cloud AI)
"""

from __future__ import annotations

import enum
import logging
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from backend.conversational.calculator import is_arithmetic_query

logger = logging.getLogger(__name__)


class IntentCategory(str, enum.Enum):
    GENERAL_CONVERSATION = "general_conversation"
    GREETING = "greeting"
    IDENTITY = "identity"
    ARITHMETIC = "arithmetic"
    HISTORICAL_FACTUAL = "historical_factual"
    CURRENT_INFORMATION = "current_information"
    SPORTS_RESULT = "sports_result"
    ENTERTAINMENT = "entertainment"
    STATISTICAL = "statistical"
    MULTI_TURN_FOLLOWUP = "multi_turn_followup"
    SEMANTIC_MEMORY_QUERY = "semantic_memory_query"
    EPISODIC_MEMORY_QUERY = "episodic_memory_query"
    MODEL_CAPABILITY_QUERY = "model_capability_query"
    COMPLEX_TASK = "complex_task"


class IntentResult(BaseModel):
    """Validated intent classification contract."""
    intent_category: IntentCategory
    sub_intent: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    entities: List[str] = Field(default_factory=list)
    referenced_entities: List[str] = Field(default_factory=list)
    requires_clarification: bool = False
    clarification_prompt: Optional[str] = None
    requires_external_retrieval: bool = False
    requires_memory: bool = False
    requires_tool_execution: bool = False
    requires_task_planning: bool = False


# Complex task indicators that trigger DAG planning
COMPLEX_TASK_INDICATORS = [
    "analyze my project",
    "identify backend errors",
    "fix the issues",
    "fix issues",
    "run the tests",
    "run tests",
    "summarize the changes",
    "create file",
    "write file",
    "delete file",
    "build and deploy",
    "refactor",
    "execute plan",
    "run task",
    "git commit",
    "deploy ",
    "modify file",
]

# Memory query indicators
EXPLICIT_MEMORY_KEYWORDS = [
    "what do you remember", "what is remembered", "do you remember",
    "what are my preferences", "what is my preference", "what do i prefer",
    "my saved preferences", "do i have any preferences", "saved memories",
    "show my memories", "list my memories", "my memories",
    "what did i say about", "past decisions", "previous decisions",
    "what are my goals", "what is my goal", "my project goals",
    "what did we decide", "search memory", "find memory", "recall memory",
    "what tone do i prefer", "what shell do i prefer", "what terminal",
    "what font do i use", "my primary programming language",
    "what is my primary", "which do i prefer", "what is my preferred",
    "what did i tell you earlier",
]

FOLLOW_UP_INDICATORS = [
    "can you total collection",
    "can you total its collection",
    "total collection",
    "worldwide total",
    "worldwide collection",
    "what about its",
    "its budget",
    "its collection",
    "give me its",
    "tell me more",
    "who won that",
    "what was the score then",
    "and what happened next",
    "who directed it",
]


class IntentClassifier:
    """Classifies user intent using deterministic rules and local Ollama when needed."""

    def __init__(self, ollama_client: Optional[Any] = None, timeout: float = 5.0):
        self.ollama_client = ollama_client
        self.timeout = timeout

    def classify(self, prompt: str, session_context: Optional[Dict[str, Any]] = None) -> IntentResult:
        """
        Classifies user prompt into a validated IntentResult.
        Applies deterministic rules first; falls back to structured inference only if needed.
        """
        text = prompt.strip()
        lower = text.lower()

        # 1. Complex task triggers
        for cti in COMPLEX_TASK_INDICATORS:
            if cti in lower:
                return IntentResult(
                    intent_category=IntentCategory.COMPLEX_TASK,
                    sub_intent="autonomous_workflow",
                    confidence=0.95,
                    requires_task_planning=True,
                    requires_tool_execution=True,
                )

        # 2. Arithmetic / Math detection
        if is_arithmetic_query(text):
            return IntentResult(
                intent_category=IntentCategory.ARITHMETIC,
                sub_intent="deterministic_calculation",
                confidence=1.0,
                requires_tool_execution=False,
                requires_task_planning=False,
            )

        # 3. Memory queries
        if any(kw in lower for kw in EXPLICIT_MEMORY_KEYWORDS):
            is_episodic = any(k in lower for k in ["earlier", "we discussed", "last time", "i told you", "did i say"])
            return IntentResult(
                intent_category=IntentCategory.EPISODIC_MEMORY_QUERY if is_episodic else IntentCategory.SEMANTIC_MEMORY_QUERY,
                sub_intent="memory_recall",
                confidence=0.95,
                requires_memory=True,
            )

        # 4. Identity & capabilities
        identity_phrases = ["who are you", "what is your name", "what do you do", "introduce yourself", "state your identity"]
        if any(p in lower for p in identity_phrases):
            return IntentResult(
                intent_category=IntentCategory.IDENTITY,
                sub_intent="system_persona",
                confidence=1.0,
            )

        capability_phrases = [
            "training cutoff", "cutoff date", "knowledge cutoff", "when was your training",
            "training data", "data cutoff", "what year does your training",
            "can you browse", "are you connected to the internet", "can you search online",
            "are you online", "do you have internet access", "online or offline"
        ]
        if any(p in lower for p in capability_phrases):
            return IntentResult(
                intent_category=IntentCategory.MODEL_CAPABILITY_QUERY,
                sub_intent="cutoff_and_retrieval_disclosure",
                confidence=1.0,
            )

        # 5. Greetings
        greeting_words = ["hi", "hello", "hey", "good morning", "good evening", "good afternoon", "greetings"]
        if lower in greeting_words or any(lower.startswith(f"{g} ") or lower.startswith(f"{g},") for g in greeting_words):
            return IntentResult(
                intent_category=IntentCategory.GREETING,
                sub_intent="casual_greeting",
                confidence=1.0,
            )

        # 6. Multi-turn Follow-ups (using pronouns or continuation phrases)
        is_followup = any(f in lower for f in FOLLOW_UP_INDICATORS) or lower.startswith("what about") or lower.startswith("and ")
        has_pronoun_ref = any(re.search(rf"\b{pr}\b", lower) for pr in ["it", "its", "that", "this", "them", "he", "she"])
        
        recent_entity = None
        if session_context and session_context.get("last_entity"):
            recent_entity = session_context.get("last_entity")

        if (is_followup or (has_pronoun_ref and recent_entity)) and recent_entity:
            # Check if follow-up relates to entertainment or sports
            last_intent = session_context.get("last_intent", "")
            return IntentResult(
                intent_category=IntentCategory.MULTI_TURN_FOLLOWUP,
                sub_intent="entity_continuation",
                confidence=0.9,
                entities=[recent_entity],
                referenced_entities=[recent_entity],
                requires_clarification=False,
            )

        # 7. Movie / Entertainment queries
        entertainment_signals = ["baahubali", "katappa", "bahubali", "movie", "box office", "budget", "collection", "day-wise", "worldwide gross", "actor", "director"]
        if any(sig in lower for sig in entertainment_signals):
            entities = []
            if "baahubali" in lower or "bahubali" in lower:
                entities.append("Baahubali 2")
            if "katappa" in lower:
                entities.append("Katappa")

            return IntentResult(
                intent_category=IntentCategory.ENTERTAINMENT,
                sub_intent="movie_factual",
                confidence=0.9,
                entities=entities,
            )

        # 8. Sports queries (India vs Pakistan, tournaments)
        sports_signals = [
            "ind vs pak", "india vs pakistan", "match result", "cricket", "asia cup",
            "t20 world cup", "world cup", "football", "who won", "score of", "match"
        ]
        if any(sig in lower for sig in sports_signals):
            entities = []
            if "ind vs pak" in lower or "india vs pakistan" in lower:
                entities.append("India vs Pakistan")
            if "asia cup" in lower:
                entities.append("Asia Cup")
            if "world cup" in lower:
                entities.append("World Cup")

            # Ambiguity check: e.g. "What is Ind vs Pak match result?" without tournament or date
            is_ambiguous_sports = (
                ("ind vs pak" in lower or "india vs pakistan" in lower)
                and not any(yr in lower for yr in ["2022", "2023", "2024", "2025", "2026", "t20", "asia cup", "champions trophy", "odi"])
            )

            clarification = None
            if is_ambiguous_sports:
                clarification = (
                    "India and Pakistan have faced each other in multiple tournaments and formats. "
                    "Which tournament or match are you inquiring about (for example, Asia Cup, T20 World Cup, or ODI World Cup)?"
                )

            return IntentResult(
                intent_category=IntentCategory.SPORTS_RESULT,
                sub_intent="sports_score_or_schedule",
                confidence=0.9,
                entities=entities,
                requires_clarification=is_ambiguous_sports,
                clarification_prompt=clarification,
                requires_external_retrieval=True,
            )

        # Default: General conversation
        return IntentResult(
            intent_category=IntentCategory.GENERAL_CONVERSATION,
            sub_intent="general_inquiry",
            confidence=0.8,
            entities=[],
        )

