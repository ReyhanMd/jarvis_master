"""
Master Planner - Symbiotic Controller

This module implements the "Master-Grounding-Vision" architecture (Symbiotic OS).
It coordinates the Perception Layer (GroundingAgent, AnomalyVisionAgent) to "understand"
the user's context before making routing decisions or synthesizing solutions.

Key Features:
1. Master-Grounding-Vision Triad: Coordinates search (Grounding) and observation (Vision).
2. Resource-Bounded Reasoning: Uses a budget ($b$) to prevent infinite loops.
3. Human-in-the-Loop: Asks for help when grounding confidence is low.
"""

import json
import re
import time
import threading
from typing import Optional, List, Dict, Any

from langchain_google_genai import ChatGoogleGenerativeAI
from shail.core.types import (
    TaskRequest,
    RoutingDecision,
    GroundingResult,
    VisionObservation,
    UserGuidanceRequest,
)
from shail.core.agent_registry import format_capabilities_for_llm, list_all_agents, AGENT_CAPABILITIES
from apps.shail.settings import get_settings
from shail.memory import rag

# New Perception Imports
from shail.perception.grounding_agent import GroundingAgent
from shail.perception.vision_agent import VisionObservationAgent
from shail.perception.native_bridge import get_native_bridge


class MasterPlanner:
    """
    Symbiotic Controller that routes requests and coordinates perception.
    
    Uses Gemini to analyze the user's request and match it against agent
    capabilities to make intelligent routing decisions.
    """
    
    def __init__(self):
        settings = get_settings()
        self.llm = ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.gemini_api_key or None,
            temperature=0.3  # Lower temperature for consistent routing decisions
        )
        self.agent_capabilities = format_capabilities_for_llm()
        self.available_agents = list_all_agents()
        
        # Initialize Perception Layer (Native Bridge)
        bridge = get_native_bridge()
        bridge.start()
        self.buffer = bridge.buffer
        self.grounding_agent = GroundingAgent(self.buffer)
        self.vision_agent = VisionObservationAgent(
            connector=bridge.connector,
            buffer=self.buffer,
        )
        
        # Build keyword lookup maps for fast routing
        self._build_keyword_maps()
    
    def route_request(self, req: TaskRequest) -> RoutingDecision:
        """
        Analyze the user request and route it to the most appropriate agent.
        Now includes the Symbiotic Reasoning Loop for context-heavy requests.
        
        Uses a multi-tier approach:
        1. Explicit mode (user requested specific agent)
        2. Fast keyword-based routing (< 10ms)
        3. Symbiotic Reasoning Loop (Context/Perception)
        4. LLM-powered routing for ambiguous requests (1-3s with timeout)
        """
        # TIER 1: If user explicitly specified a mode, honor it
        if req.mode and req.mode != "auto" and req.mode in self.available_agents:
            return RoutingDecision(
                agent=req.mode,
                confidence=0.95,
                rationale=f"User explicitly requested {req.mode} agent"
            )
        
        # TIER 2: Fast keyword-based routing (< 10ms)
        fast_decision = self._fast_keyword_route(req.text)
        if fast_decision:
            return fast_decision
            
        # TIER 3: Symbiotic Reasoning Loop (The "Brain")
        # If the request implies "what happened?" or "fix this error", we use the triad.
        # Simple heuristic: Does it need context?
        needs_context = self._check_if_needs_context(req.text)
        
        if needs_context:
            return self._execute_symbiotic_loop(req.text)
        
        # TIER 4: LLM-powered routing for ambiguous requests (1-3s with timeout)
        return self._llm_route(req.text)

    def _check_if_needs_context(self, text: str) -> bool:
        """Simple heuristic to decide if we need the Master-Grounding-Vision loop."""
        triggers = ["error", "bug", "crash", "saw", "what happened", "fix this", "why is"]
        return any(t in text.lower() for t in triggers)

    def _buffer_has_data(self) -> bool:
        try:
            return bool(self.buffer._ax_events or self.buffer._frames)
        except Exception:
            return False

    def _retrieve_memory_context(self, query: str) -> str:
        try:
            results = rag.search(query, k=3)
        except Exception:
            results = []
        if not results:
            return ""
        lines = []
        for content, score, metadata in results:
            snippet = content.replace("\n", " ").strip()
            if len(snippet) > 200:
                snippet = snippet[:200] + "..."
            lines.append(f"- ({score:.2f}) {snippet}")
        return "\n".join(lines)

    def _execute_symbiotic_loop(self, user_query: str) -> RoutingDecision:
        """
        Executes the Master-Grounding-Vision Triad + Swaraj Loop (Generate-Verify-Refine).
        """
        print(f"[SymbioticController] Starting reasoning loop for: '{user_query}'")
        MAX_GLANCES = 3
        CONFIDENCE_ACCEPT = 0.6
        CONFIDENCE_ESCALATE = 0.4

        # --- PHASE 1: Perception (Gather Context) ---
        if not self._buffer_has_data():
            print("[SymbioticController] Warning: Grounding buffer is empty. Check native services.")
        grounding_result = self.grounding_agent.find_event(user_query, max_glances=MAX_GLANCES)

        # If we failed to localize confidently, escalate to user guidance
        if not grounding_result.segment or grounding_result.confidence < CONFIDENCE_ESCALATE:
            guidance = UserGuidanceRequest(
                original_query=user_query,
                attempts=MAX_GLANCES,
                last_confidence=grounding_result.confidence,
                suggested_clarifications=[
                    "Can you describe when this happened?",
                    "Which app/window showed the error?",
                    "Any keywords from the error message?",
                ],
            )
            return RoutingDecision(
                agent="user_guidance",
                confidence=grounding_result.confidence,
                rationale="Could not locate relevant screen context after 3 glances.",
                guidance_request=guidance,
            )

        # 2. Vision
        vision_obs = None
        if grounding_result.segment:
            vision_obs = self.vision_agent.observe(grounding_result.segment, focus_prompt=user_query)

        # Context Synthesis
        context = f"User Query: {user_query}\n"
        if grounding_result.segment:
            context += f"History: {grounding_result.segment.story}\n"
        if vision_obs:
            context += f"Observation: {vision_obs.text}\n"
            if vision_obs.is_anomaly:
                context += f"Anomalies Detected: {vision_obs.detected_anomalies}\n"
        memory_context = self._retrieve_memory_context(user_query)
        if memory_context:
            context += f"Memory:\n{memory_context}\n"

        # --- PHASE 2: Swaraj Loop (Generate -> Verify -> Refine) ---
        budget = 3
        loop_count = 0
        current_solution = None

        from shail.agents.detective_agent import AnomalyBiasedDetective

        detective = AnomalyBiasedDetective()

        while loop_count < budget:
            loop_count += 1
            print(f"[SwarajLoop] Iteration {loop_count}/{budget}")

            gen_prompt = self._build_generation_prompt(context, current_solution)
            try:
                response = self._invoke_llm_with_timeout(gen_prompt, timeout_seconds=8.0)
                current_solution = response.content if hasattr(response, "content") else str(response)
            except Exception as exc:
                err = self._format_llm_error(exc)
                print(f"[SwarajLoop] LLM error: {err}")
                return RoutingDecision(
                    agent="code",
                    confidence=0.3,
                    rationale=f"LLM error during Swaraj Loop: {err}",
                )

            verdict = detective.investigate(current_solution, context)

            if verdict.passed:
                print(f"[SwarajLoop] Solution Verified! Confidence: {verdict.confidence}")
                return RoutingDecision(
                    agent="code",
                    confidence=0.99,
                    rationale=f"Swaraj Solution Verified: {current_solution[:100]}...",
                )
            else:
                print(f"[SwarajLoop] Detective Rejected: {verdict.bug_narrative}")
                context += f"\nPrevious Attempt Failed:\n{verdict.bug_narrative}\n"

        # Fallback: best effort
        return RoutingDecision(
            agent="code",
            confidence=0.7,
            rationale="Swaraj Loop exhausted budget. Returning best effort solution.",
        )

    def _build_generation_prompt(self, context: str, current_solution: Optional[str]) -> str:
        """Helper to build prompt for code generation."""
        if current_solution:
            return f"""Refine the previous code solution based on the feedback.
            
Context: {context}

Previous Solution:
{current_solution}

Return ONLY the corrected Python code."""
        else:
            return f"""Generate a Python code solution for the following request.
            
Context: {context}

Return ONLY the Python code."""
    
    def _build_keyword_maps(self):
        """
        Build keyword lookup maps from agent registry for fast routing.
        This is called once during initialization.
        """
        self._keyword_to_agent = {}
        
        # Build reverse lookup: keyword -> agent
        for agent_id, info in AGENT_CAPABILITIES.items():
            keywords = info.get("keywords", [])
            for keyword in keywords:
                # Store agent with priority (first match wins, but we can enhance this)
                if keyword not in self._keyword_to_agent:
                    self._keyword_to_agent[keyword] = agent_id
    
    def _fast_keyword_route(self, user_text: str) -> Optional[RoutingDecision]:
        """
        Fast keyword-based routing for obvious requests.
        
        Returns RoutingDecision if a clear match is found, None otherwise.
        This avoids expensive LLM calls for simple requests like "open Calculator".
        
        Args:
            user_text: User's request text
            
        Returns:
            RoutingDecision if match found, None if ambiguous
        """
        text_lower = user_text.lower()
        
        # Desktop control keywords → FriendAgent (highest priority for obvious desktop ops)
        desktop_keywords = [
            "click", "mouse", "type", "keyboard", "scroll", "window", "focus",
            "open safari", "open calculator", "open app", "press key", "press cmd",
            "move mouse", "right click", "left click", "double click",
            "hotkey", "shortcut", "desktop control", "hands-free"
        ]
        if any(kw in text_lower for kw in desktop_keywords):
            return RoutingDecision(
                agent="friend",
                confidence=0.95,
                rationale="Fast keyword match: desktop control operation"
            )
        
        # File operations → CodeAgent
        file_keywords = [
            "list files", "create file", "read file", "delete file", "write file",
            "create directory", "mkdir", "rm -rf", "ls -la", "cat", "grep",
            "file operation", "directory", "folder"
        ]
        if any(kw in text_lower for kw in file_keywords):
            return RoutingDecision(
                agent="code",
                confidence=0.95,
                rationale="Fast keyword match: file system operation"
            )
        
        # Code generation keywords → CodeAgent
        code_keywords = [
            "create a script", "write code", "build", "python script", "javascript",
            "html", "run command", "execute", "programming", "develop",
            "next.js", "react", "flask", "fastapi", "api", "website", "app"
        ]
        if any(kw in text_lower for kw in code_keywords):
            return RoutingDecision(
                agent="code",
                confidence=0.95,
                rationale="Fast keyword match: code generation or development"
            )
        
        # Research keywords → ResearchAgent
        research_keywords = [
            "search for", "find information", "research", "paper", "literature",
            "summarize", "article", "journal", "citation", "academic"
        ]
        if any(kw in text_lower for kw in research_keywords):
            return RoutingDecision(
                agent="research",
                confidence=0.90,
                rationale="Fast keyword match: research or information gathering"
            )
        
        # Biology keywords → BioAgent
        bio_keywords = [
            "protein", "crispr", "gene", "dna", "rna", "molecular", "biology",
            "drug", "sequence", "fold", "bioinformatics"
        ]
        if any(kw in text_lower for kw in bio_keywords):
            return RoutingDecision(
                agent="bio",
                confidence=0.90,
                rationale="Fast keyword match: biological or bioinformatics task"
            )
        
        # Robotics keywords → RoboAgent
        robo_keywords = [
            "cad", "robot", "solidworks", "freecad", "ros", "kinematics",
            "mechanical", "drone", "robotics", "3d model"
        ]
        if any(kw in text_lower for kw in robo_keywords):
            return RoutingDecision(
                agent="robo",
                confidence=0.90,
                rationale="Fast keyword match: robotics or CAD task"
            )
        
        # Plasma/Physics keywords → PlasmaAgent
        plasma_keywords = [
            "plasma", "fusion", "openfoam", "simulink", "matlab", "cfd",
            "fluid", "physics", "simulation", "electromagnetic"
        ]
        if any(kw in text_lower for kw in plasma_keywords):
            return RoutingDecision(
                agent="plasma",
                confidence=0.90,
                rationale="Fast keyword match: plasma physics or simulation"
            )
        
        # If no clear match, return None to use LLM routing
        return None
    
    def _llm_route(self, user_text: str) -> RoutingDecision:
        """
        LLM-powered routing for ambiguous requests.
        
        Uses Gemini to analyze the request and make intelligent routing decisions.
        Includes timeout handling (5 seconds max) and graceful fallback.
        
        Args:
            user_text: User's request text
            
        Returns:
            RoutingDecision with selected agent
        """
        # Build the routing prompt
        prompt = self._build_routing_prompt(user_text)
        
        # Thread-safe result storage
        result_container = {"response": None, "error": None, "completed": False}
        
        def invoke_llm():
            """Wrapper function to invoke LLM in a separate thread."""
            try:
                result_container["response"] = self.llm.invoke(prompt)
                result_container["completed"] = True
            except Exception as e:
                result_container["error"] = e
                result_container["completed"] = True
        
        try:
            # Start LLM call in a separate thread
            start_time = time.time()
            llm_thread = threading.Thread(target=invoke_llm, daemon=True)
            llm_thread.start()
            
            # Wait for completion with timeout (5 seconds)
            llm_thread.join(timeout=5.0)
            elapsed = time.time() - start_time
            
            # Check if thread is still alive (timed out)
            if llm_thread.is_alive():
                # Thread is still running - timeout occurred
                print(f"[MasterPlanner] Warning: LLM routing timed out after {elapsed:.2f}s")
                return RoutingDecision(
                    agent="code",
                    confidence=0.4,
                    rationale="LLM routing timed out (>5s), defaulted to code agent"
                )
            
            # Check for errors
            if result_container["error"]:
                raise result_container["error"]
            
            # Get response
            response = result_container["response"]
            if response is None:
                raise ValueError("LLM returned None response")
            
            # Log if LLM call took too long (for monitoring)
            if elapsed > 3.0:
                print(f"[MasterPlanner] Warning: LLM routing took {elapsed:.2f}s (slow)")
            
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Parse JSON from response
            decision = self._parse_llm_response(response_text)
            
            # Validate agent name
            if decision.agent not in self.available_agents:
                # Fallback to code agent if invalid
                return RoutingDecision(
                    agent="code",
                    confidence=0.5,
                    rationale=f"Invalid agent '{decision.agent}' returned by LLM, defaulted to code"
                )
            
            return decision
            
        except TimeoutError:
            # LLM call timed out - fallback to code agent
            return RoutingDecision(
                agent="code",
                confidence=0.4,
                rationale="LLM routing timed out (>5s), defaulted to code agent"
            )
        except Exception as e:
            # Fallback to code agent on any error
            error_msg = self._format_llm_error(e)
            print(f"[MasterPlanner] Error during LLM routing: {error_msg}")
            return RoutingDecision(
                agent="code",
                confidence=0.4,
                rationale=f"Master Planner error: {error_msg}, defaulted to code agent"
            )
    
    def _build_routing_prompt(self, user_text: str) -> str:
        """
        Build the prompt for the routing LLM.
        
        Args:
            user_text: User's request text
            
        Returns:
            Formatted prompt string
        """
        memory_context = self._retrieve_memory_context(user_text)
        prompt = f"""You are ShailCore, the master planner for a multi-agent AI system called Shail.

Your ONLY job is to analyze a user's request and determine which single agent should handle it.

{self.agent_capabilities}

User Request: "{user_text}"

Relevant Memory (if any):
{memory_context or "None"}

Analyze the user's request and determine which agent is best suited to handle it.

You MUST return ONLY a valid JSON object with this EXACT structure:
{{
    "agent": "code|bio|robo|plasma|research|friend",
    "confidence": 0.0-1.0,
    "rationale": "Brief explanation of why this agent was chosen (1-2 sentences)"
}}

Important guidelines:
- Choose the agent whose capabilities best match the request
- Confidence should reflect how certain you are (0.7+ for clear matches, 0.5-0.7 for ambiguous)
- The rationale should explain the reasoning clearly
- If the request could match multiple agents, choose the most specialized one
- Default to "code" only if no other agent clearly fits

Return ONLY the JSON object, no other text:"""
        
        return prompt

    def _invoke_llm_with_timeout(self, prompt: str, timeout_seconds: float = 8.0):
        result_container = {"response": None, "error": None}

        def invoke_llm():
            try:
                result_container["response"] = self.llm.invoke(prompt)
            except Exception as e:
                result_container["error"] = e

        llm_thread = threading.Thread(target=invoke_llm, daemon=True)
        llm_thread.start()
        llm_thread.join(timeout=timeout_seconds)

        if llm_thread.is_alive():
            raise TimeoutError(f"LLM timeout after {timeout_seconds:.1f}s")
        if result_container["error"]:
            raise result_container["error"]
        if result_container["response"] is None:
            raise RuntimeError("LLM returned no response")
        return result_container["response"]

    def _format_llm_error(self, exc: Exception) -> str:
        settings = get_settings()
        if not settings.gemini_api_key:
            return "Missing API Key (GEMINI_API_KEY is empty)"
        message = str(exc)
        if "timed out" in message.lower():
            return f"Timeout: {message}"
        return message
    
    def _parse_llm_response(self, response_text: str) -> RoutingDecision:
        """
        Parse the LLM's response and extract routing decision.
        
        Args:
            response_text: Raw response from LLM
            
        Returns:
            RoutingDecision object
            
        Raises:
            ValueError: If response cannot be parsed
        """
        # Try to extract JSON from the response
        # The LLM might return JSON wrapped in markdown code blocks or extra text
        
        # Strategy 1: Remove markdown code blocks if present
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Strategy 2: Find JSON object by looking for opening brace to closing brace
            # Use a more sophisticated approach to handle nested structures
            brace_count = 0
            start_idx = -1
            json_str = None
            for i, char in enumerate(response_text):
                if char == '{':
                    if brace_count == 0:
                        start_idx = i
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0 and start_idx >= 0:
                        json_str = response_text[start_idx:i+1]
                        break
            
            if json_str is None:
                # Strategy 3: Last resort - try to parse the entire response
                json_str = response_text.strip()
                # Try to find JSON-like structure
                json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*"agent"[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
        
        try:
            parsed = json.loads(json_str)
            
            # Validate required fields
            if "agent" not in parsed:
                raise ValueError("Missing 'agent' field in LLM response")
            
            return RoutingDecision(
                agent=parsed["agent"],
                confidence=float(parsed.get("confidence", 0.7)),
                rationale=parsed.get("rationale", "Master Planner decision")
            )
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse JSON from LLM response: {e}. Response: {response_text[:200]}")
        except (KeyError, ValueError) as e:
            raise ValueError(f"Invalid routing decision format: {e}")
