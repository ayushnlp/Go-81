"""
Session Management and Multi-Turn Context Tracking for Project Go 81.
Stage 5 Intelligent Conversational Engine:
- Multi-session isolation: each session_id maintains distinct conversation context
- Bounded context window: retains recent relevant turns to prevent LLM context saturation
- Entity tracking and reference resolution: maps pronouns ('its', 'that movie', 'it') to discussed subjects
- Distinction between transient conversation history and durable encrypted memory
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import re

logger = logging.getLogger(__name__)


@dataclass
class SessionTurn:
    turn_id: str
    user_prompt: str
    assistant_response: str
    intent: Optional[str] = None
    entities: List[str] = field(default_factory=list)
    timestamp_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class SessionState:
    session_id: str
    turns: List[SessionTurn] = field(default_factory=list)
    last_entity: Optional[str] = None
    last_intent: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ConversationSessionManager:
    """Thread-safe manager for conversational sessions."""

    MAX_STORED_TURNS = 10
    MAX_PROMPT_TURNS = 4

    def __init__(self):
        self._sessions: Dict[str, SessionState] = {}
        self._lock = threading.Lock()

    def get_or_create_session(self, session_id: Optional[str] = None) -> SessionState:
        sid = (session_id or "default").strip()
        with self._lock:
            if sid not in self._sessions:
                self._sessions[sid] = SessionState(session_id=sid)
            return self._sessions[sid]

    def record_turn(
        self,
        session_id: str,
        user_prompt: str,
        assistant_response: str,
        intent: Optional[str] = None,
        entities: Optional[List[str]] = None,
    ) -> SessionTurn:
        """Records a completed conversation turn and updates tracked entities."""
        sid = (session_id or "default").strip()
        entities = entities or []

        turn = SessionTurn(
            turn_id=f"turn-{uuid.uuid4().hex[:8]}",
            user_prompt=user_prompt,
            assistant_response=assistant_response,
            intent=intent,
            entities=entities,
        )

        with self._lock:
            if sid not in self._sessions:
                self._sessions[sid] = SessionState(session_id=sid)
            state = self._sessions[sid]
            state.turns.append(turn)
            
            # Prune turns beyond max bounded window
            if len(state.turns) > self.MAX_STORED_TURNS:
                state.turns = state.turns[-self.MAX_STORED_TURNS:]

            # Update tracked active entity if mentioned
            if entities:
                state.last_entity = entities[0]
            if intent:
                state.last_intent = intent
            state.updated_at = datetime.now(timezone.utc)

        return turn

    def resolve_references(self, prompt: str, session_id: str) -> Dict[str, Any]:
        """
        Resolves pronouns ('its', 'that movie', 'it') using active session context.
        Returns a dictionary with resolved prompt and identified entity.
        """
        sid = (session_id or "default").strip()
        with self._lock:
            state = self._sessions.get(sid)
            last_entity = state.last_entity if state else None

        if not last_entity:
            return {"resolved_prompt": prompt, "entity": None, "was_resolved": False}

        p_lower = prompt.lower()
        was_resolved = False
        resolved_text = prompt

        # If user refers to 'its total collection', 'its worldwide', 'that movie', resolve to last entity
        pronoun_patterns = [
            (r"\bits\s+total\s+worldwide\s+collection\b", f"total worldwide collection of {last_entity}"),
            (r"\bits\s+total\s+collection\b", f"total collection of {last_entity}"),
            (r"\bits\s+worldwide\s+collection\b", f"worldwide collection of {last_entity}"),
            (r"\bits\s+budget\b", f"budget of {last_entity}"),
            (r"\bits\s+collection\b", f"collection of {last_entity}"),
            (r"\bthat\s+movie\b", last_entity),
            (r"\bthis\s+movie\b", last_entity),
            (r"\bthat\s+match\b", last_entity),
        ]

        for pattern, replacement in pronoun_patterns:
            if re.search(pattern, resolved_text, flags=re.IGNORECASE):
                resolved_text = re.sub(pattern, replacement, resolved_text, flags=re.IGNORECASE)
                was_resolved = True

        return {
            "resolved_prompt": resolved_text,
            "entity": last_entity,
            "was_resolved": was_resolved,
        }

    def get_recent_messages_for_llm(self, session_id: str, max_turns: Optional[int] = None) -> List[Dict[str, str]]:
        """
        Builds a bounded list of recent message pairs for Ollama context injection.
        Guarantees that history remains within strict token/turn boundaries.
        """
        sid = (session_id or "default").strip()
        limit = max_turns or self.MAX_PROMPT_TURNS

        with self._lock:
            state = self._sessions.get(sid)
            if not state or not state.turns:
                return []
            selected_turns = state.turns[-limit:]

        messages: List[Dict[str, str]] = []
        for t in selected_turns:
            messages.append({"role": "user", "content": t.user_prompt})
            messages.append({"role": "assistant", "content": t.assistant_response})

        return messages

    def clear_session(self, session_id: str) -> None:
        """Clears transient context for a session."""
        sid = (session_id or "default").strip()
        with self._lock:
            if sid in self._sessions:
                del self._sessions[sid]


# Global singleton
_session_manager = ConversationSessionManager()


def get_session_manager() -> ConversationSessionManager:
    return _session_manager

