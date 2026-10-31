"""
Intelligent Conversational Engine for Project Go 81.
Stage 5 Core Engine:
- Orchestrates intent classification, session context tracking, deterministic utilities,
  grounded factual knowledge guards, memory integration, and local Ollama reasoning.
- Enforces strict local-first sovereignty with zero cloud AI calls.
- Provides verifiable execution traces and transparent evidence metadata.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional
import httpx

from app.memory.service import MemoryService, query_relevant_context
from backend.conversational.calculator import evaluate_math_expression, is_arithmetic_query
from backend.conversational.intent import IntentCategory, IntentClassifier, IntentResult
from backend.conversational.knowledge_guard import KnowledgeGuard
from backend.conversational.session_manager import ConversationSessionManager, get_session_manager
from backend.conversational.timezone import format_local_timestamp, get_system_time_context
from backend.ollama_client import OllamaClient, OllamaConfig

logger = logging.getLogger(__name__)


class IntelligentConversationalEngine:
    """
    Main conversational engine providing context awareness, multi-turn tracking,
    deterministic arithmetic, grounded factual accuracy, and local Ollama inference.
    """

    def __init__(
        self,
        ollama_endpoint: Optional[str] = None,
        chat_model: Optional[str] = None,
        session_manager: Optional[ConversationSessionManager] = None,
    ):
        self.ollama_endpoint = (
            ollama_endpoint
            or os.environ.get("OLLAMA_BASE_URL")
            or os.environ.get("OLLAMA_ENDPOINT")
            or "http://127.0.0.1:11434"
        ).rstrip("/")
        self.chat_model = (
            chat_model
            or os.environ.get("OLLAMA_CHAT_MODEL")
            or os.environ.get("GO81_MODEL")
            or "llama3.2:3b"
        )
        self.session_manager = session_manager or get_session_manager()
        self.intent_classifier = IntentClassifier()
        self.knowledge_guard = KnowledgeGuard()

        # Configurable timeouts
        self.conversational_timeout = float(os.environ.get("GO81_CONV_TIMEOUT", "25.0"))
        self.connect_timeout = float(os.environ.get("GO81_CONNECT_TIMEOUT", "3.0"))

    def handle_message(
        self,
        prompt: str,
        mode: str = "chat",
        session_id: Optional[str] = None,
        memory_service: Optional[MemoryService] = None,
        memory_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Processes a conversational message through the multi-stage pipeline:
        1. Multi-turn reference resolution
        2. Intent classification
        3. Deterministic calculation (if arithmetic)
        4. Factual knowledge guard (if entertainment, sports, or capability inquiry)
        5. Verified memory retrieval (if personal query or memory mode)
        6. Bounded local Ollama reasoning (for general conversational questions)
        7. Session state update
        """
        sid = (session_id or "default").strip()
        raw_prompt = prompt.strip()

        # Step 1: Multi-turn reference resolution
        ref_resolution = self.session_manager.resolve_references(raw_prompt, sid)
        resolved_prompt = ref_resolution["resolved_prompt"]
        active_entity = ref_resolution["entity"]

        # Retrieve session context for classifier
        session_state = self.session_manager.get_or_create_session(sid)
        session_ctx = {
            "last_entity": session_state.last_entity,
            "last_intent": session_state.last_intent,
        }

        # Step 2: Intent classification
        intent_res = self.intent_classifier.classify(resolved_prompt, session_context=session_ctx)

        # Merge entities discovered
        discovered_entities = list(set(intent_res.entities + ([active_entity] if active_entity else [])))

        intent_data = intent_res.model_dump() if hasattr(intent_res, "model_dump") else intent_res.dict()
        # Step 3: Deterministic Arithmetic Utility
        if intent_res.intent_category == IntentCategory.ARITHMETIC or is_arithmetic_query(resolved_prompt):
            calc_res = evaluate_math_expression(resolved_prompt)
            if calc_res and calc_res.success:
                answer = f"**Calculation:**\n{calc_res.formatted}"
                self.session_manager.record_turn(
                    session_id=sid,
                    user_prompt=raw_prompt,
                    assistant_response=answer,
                    intent=intent_res.intent_category.value,
                    entities=discovered_entities,
                )
                return {
                    "content": answer,
                    "thought_trace": f"Evaluated deterministic expression safely via SafeCalculator: {calc_res.formatted}",
                    "cited_memory_ids": [],
                    "intent": intent_data,
                    "evidence": [{"type": "deterministic_math", "expression": calc_res.expression, "result": calc_res.result}],
                    "retrieval_status": "not_required",
                    "session_id": sid,
                }
            elif calc_res and calc_res.error:
                answer = f"**Calculation Error:** {calc_res.error}"
                self.session_manager.record_turn(
                    session_id=sid,
                    user_prompt=raw_prompt,
                    assistant_response=answer,
                    intent=intent_res.intent_category.value,
                    entities=discovered_entities,
                )
                return {
                    "content": answer,
                    "thought_trace": f"Calculation error handled deterministically: {calc_res.error}",
                    "cited_memory_ids": [],
                    "intent": intent_data,
                    "evidence": [],
                    "retrieval_status": "not_required",
                    "session_id": sid,
                }

        # Step 4: Clarification check (e.g. Ambiguous sports matches)
        if intent_res.requires_clarification and intent_res.clarification_prompt:
            clarification_answer = intent_res.clarification_prompt
            self.session_manager.record_turn(
                session_id=sid,
                user_prompt=raw_prompt,
                assistant_response=clarification_answer,
                intent=intent_res.intent_category.value,
                entities=discovered_entities,
            )
            return {
                "content": clarification_answer,
                "thought_trace": "Detected ambiguous question requiring user clarification.",
                "cited_memory_ids": [],
                "intent": intent_data,
                "evidence": [],
                "retrieval_status": "clarification_requested",
                "session_id": sid,
            }

        # Step 5: Factual Knowledge Guard (Baahubali, Katappa, Cutoff, Sports)
        guard_response = self.knowledge_guard.evaluate_grounded_response(
            prompt=resolved_prompt,
            intent_category=intent_res.intent_category.value,
            resolved_entity=active_entity or (discovered_entities[0] if discovered_entities else None),
        )
        if guard_response:
            guard_content = guard_response["content"]
            evidence = guard_response.get("evidence", [])
            self.session_manager.record_turn(
                session_id=sid,
                user_prompt=raw_prompt,
                assistant_response=guard_content,
                intent=intent_res.intent_category.value,
                entities=discovered_entities,
            )
            return {
                "content": guard_content,
                "thought_trace": "Grounded response supplied via KnowledgeGuard to prevent LLM hallucination.",
                "cited_memory_ids": [],
                "intent": intent_data,
                "evidence": evidence,
                "retrieval_status": "offline_verified" if evidence else "offline",
                "session_id": sid,
            }

        # Step 6: Verified Memory Integration
        is_memory_mode = (mode == "memory") or (intent_res.intent_category in (IntentCategory.SEMANTIC_MEMORY_QUERY, IntentCategory.EPISODIC_MEMORY_QUERY))
        if memory_context is None:
            memory_context = query_relevant_context(resolved_prompt, memory_service=memory_service)
        cited_ids = memory_context.get("cited_memory_ids", [])

        if is_memory_mode or cited_ids:
            if is_memory_mode and not cited_ids:
                if memory_context.get("memory_available") is False:
                    content = "Memory subsystem is currently unavailable. No prior preferences or decisions could be retrieved."
                else:
                    content = "I reviewed your saved memories, but found no relevant prior preferences, goals, or decisions matching your question."
            else:
                sections = []
                if memory_context.get("preferences"):
                    p_lines = [f"- {p['subject']}: {p['predicate']} is {p['object_value']}" for p in memory_context["preferences"]]
                    sections.append("Preferences:\n" + "\n".join(p_lines))
                if memory_context.get("relevant_goals"):
                    g_lines = [f"- {g['predicate']}: {g['object_value']}" for g in memory_context["relevant_goals"]]
                    sections.append("Goals:\n" + "\n".join(g_lines))
                if memory_context.get("prior_decisions"):
                    d_lines = [f"- {d['predicate']}: {d['object_value']}" for d in memory_context["prior_decisions"]]
                    sections.append("Prior Decisions:\n" + "\n".join(d_lines))
                if memory_context.get("verified_facts"):
                    f_lines = [f"- {f['subject']} {f['predicate']} {f['object_value']}" for f in memory_context["verified_facts"]]
                    sections.append("Verified Facts:\n" + "\n".join(f_lines))
                
                memory_text = "\n\n".join(sections)
                content = f"Here is what I found in your personal memory:\n\n{memory_text}"

                # If Ollama is available, formulate grounded conversational answer with memory context
                llm_response = self._invoke_ollama_chat(
                    prompt=resolved_prompt,
                    system_override=(
                        "You are Go 81's Sovereign Personal Assistant.\n"
                        "Answer the user's question accurately using only their verified personal memories:\n"
                        f"{memory_text}\n\n"
                        "Mandatory instructions:\n"
                        "1. State the user's recorded preferences, goals, and values verbatim as recorded.\n"
                        "2. Never omit, shorten, or truncate compound/composite specifications (for example, if the preference states 'zsh with starship', state 'zsh with starship', do not say only 'zsh').\n"
                        "3. Keep the answer direct and concise."
                    ),
                    session_id=sid,
                    temperature=0.0,
                )
                if llm_response:
                    content = llm_response

            self.session_manager.record_turn(
                session_id=sid,
                user_prompt=raw_prompt,
                assistant_response=content,
                intent=intent_res.intent_category.value,
                entities=discovered_entities,
            )
            return {
                "content": content,
                "thought_trace": f"Retrieved {len(cited_ids)} verified personal memory record(s). No tool actions or approval gates triggered.",
                "cited_memory_ids": cited_ids,
                "intent": intent_data,
                "evidence": [{"type": "personal_memory", "memory_id": mid} for mid in cited_ids],
                "retrieval_status": "memory_verified",
                "session_id": sid,
            }

        # Step 7: General Conversation via Local Ollama Reasoning
        time_ctx = get_system_time_context()
        sys_prompt = (
            "You are Go 81, a Sovereign Personal AI Agent running locally on the user's machine.\n"
            f"{time_ctx['prompt_injection_summary']}\n"
            "You assist with workflow orchestration, coding, task automation, and secure local memory.\n"
            "Guidelines:\n"
            "- Answer directly, factually, and concisely.\n"
            "- If you do not have verified real-time knowledge about an event, honestly acknowledge that live verification is unavailable.\n"
            "- Never fabricate fake URLs, citations, or non-existent external sources.\n"
            "- Maintain an authentic, helpful personal assistant tone."
        )

        llm_content = self._invoke_ollama_chat(
            prompt=resolved_prompt,
            system_override=sys_prompt,
            session_id=sid,
        )

        if not llm_content:
            # Sovereign offline fallback if Ollama daemon is offline or timed out
            llm_content = (
                "I am currently operating in sovereign offline mode. "
                "Local inference on Ollama (http://127.0.0.1:11434) is unreachable or timed out. "
                "Please ensure the Ollama service is active to enable full local conversational reasoning."
            )

        self.session_manager.record_turn(
            session_id=sid,
            user_prompt=raw_prompt,
            assistant_response=llm_content,
            intent=intent_res.intent_category.value,
            entities=discovered_entities,
        )

        return {
            "content": llm_content,
            "thought_trace": f"Processed via local Ollama reasoning ({self.chat_model}). Intent: {intent_res.intent_category.value}.",
            "cited_memory_ids": [],
            "intent": intent_data,
            "evidence": [],
            "retrieval_status": "offline_reasoning",
            "session_id": sid,
        }

    def _invoke_ollama_chat(
        self,
        prompt: str,
        system_override: str,
        session_id: str,
        temperature: float = 0.2,
    ) -> Optional[str]:
        """Invokes local Ollama chat API with bounded session context and strict timeout."""
        try:
            cfg = OllamaConfig(
                base_url=self.ollama_endpoint,
                chat_model=self.chat_model,
                connect_timeout=self.connect_timeout,
                request_timeout=self.conversational_timeout,
            )
            with httpx.Client(timeout=self.conversational_timeout) as http_client:
                client = OllamaClient(config=cfg, http_client=http_client)

                # Build messages: system prompt + bounded recent turns + current prompt
                recent_messages = self.session_manager.get_recent_messages_for_llm(session_id, max_turns=3)
                messages = [{"role": "system", "content": system_override}]
                messages.extend(recent_messages)
                messages.append({"role": "user", "content": prompt})

                res = client.chat(
                    messages=messages,
                    options={"temperature": temperature},
                    timeout=self.conversational_timeout,
                )
                if res.content and res.content.strip():
                    return res.content.strip()
        except Exception as e:
            logger.warning(f"Ollama local chat inference failed or timed out: {e}")
        return None


# Global singleton
_conversational_engine: Optional[IntelligentConversationalEngine] = None


def get_conversational_engine() -> IntelligentConversationalEngine:
    global _conversational_engine
    if _conversational_engine is None:
        _conversational_engine = IntelligentConversationalEngine()
    return _conversational_engine

