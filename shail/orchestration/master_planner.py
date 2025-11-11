"""
Master Planner - LLM-powered intelligent routing system.

This module replaces the simple keyword-based routing with a Gemini-powered
"master planner" that analyzes user requests and intelligently routes them
to the most appropriate agent based on capabilities and context.
"""

import json
import re
from typing import Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from shail.core.types import TaskRequest, RoutingDecision
from shail.core.agent_registry import format_capabilities_for_llm, list_all_agents
from apps.shail.settings import get_settings


class MasterPlanner:
    """
    Master Planner LLM that routes requests to the appropriate agent.
    
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
    
    def route_request(self, req: TaskRequest) -> RoutingDecision:
        """
        Analyze the user request and route it to the most appropriate agent.
        
        Args:
            req: Task request containing user's instruction
            
        Returns:
            RoutingDecision with selected agent, confidence, and rationale
        """
        # If user explicitly specified a mode, honor it
        if req.mode and req.mode != "auto" and req.mode in self.available_agents:
            return RoutingDecision(
                agent=req.mode,
                confidence=0.95,
                rationale=f"User explicitly requested {req.mode} agent"
            )
        
        # Build the routing prompt
        prompt = self._build_routing_prompt(req.text)
        
        try:
            # Get LLM response
            response = self.llm.invoke(prompt)
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
            
        except Exception as e:
            # Fallback to code agent on any error
            return RoutingDecision(
                agent="code",
                confidence=0.4,
                rationale=f"Master Planner error: {str(e)}, defaulted to code agent"
            )
    
    def _build_routing_prompt(self, user_text: str) -> str:
        """
        Build the prompt for the routing LLM.
        
        Args:
            user_text: User's request text
            
        Returns:
            Formatted prompt string
        """
        prompt = f"""You are ShailCore, the master planner for a multi-agent AI system called Shail.

Your ONLY job is to analyze a user's request and determine which single agent should handle it.

{self.agent_capabilities}

User Request: "{user_text}"

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

