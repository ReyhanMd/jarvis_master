"""
Detective Agent (The Skeptic)

This agent implements the "Chain-of-Anomaly-Thoughts" (CoAT) logic to verify code solutions.
It has an "Inductive Anomaly Bias" - it assumes the code IS defective and tries to prove it.

Features:
1. CoAT Prompting: Explicitly lists "criminal" failure points.
2. Negative Testing: Identifies anomaly signals like infinite loops or race conditions.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from apps.shail.settings import get_settings

class DetectiveVerdict(BaseModel):
    """Verdict from the Detective Agent."""
    passed: bool = Field(..., description="Whether the code passed verification")
    anomalies: List[str] = Field(default=[], description="List of detected anomalies/bugs")
    bug_narrative: Optional[str] = Field(None, description="Detailed explanation of the failure for the coder")
    confidence: float = Field(..., description="Confidence in the verdict")

class AnomalyBiasedDetective:
    """
    The Detective. Trusts nothing. Verifies everything.
    """
    
    def __init__(self):
        settings = get_settings()
        self.llm = ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.gemini_api_key or None,
            temperature=0.1  # Low temperature for analytical rigor
        )
    
    def investigate(self, code_solution: str, context: str) -> DetectiveVerdict:
        """
        Investigate the proposed code solution using CoAT.
        
        Args:
            code_solution: The Python code to verify.
            context: The original user request/context.
            
        Returns:
            DetectiveVerdict with pass/fail status.
        """
        prompt = self._build_coat_prompt(code_solution, context)
        
        try:
            response = self.llm.invoke(prompt)
            return self._parse_verdict(response.content)
        except Exception as e:
            # If the detective crashes, we default to "Fail" for safety
            return DetectiveVerdict(
                passed=False,
                anomalies=["Detective Crash"],
                bug_narrative=f"Detective failed to analyze code: {str(e)}",
                confidence=0.0
            )

    def _build_coat_prompt(self, code: str, context: str) -> str:
        """Builds the Chain-of-Anomaly-Thoughts prompt."""
        return f"""You are the Lead Detective for a mission-critical software system.
Your job is NOT to write code, but to FIND FLAWS in the code below.

**Inductive Anomaly Bias**: You must assume the code is DEFECTIVE until proven innocent. 
Do not look for what works. Look for what breaks.

Context: "{context}"

Suspect Code:
```python
{code}
```

Method: Chain-of-Anomaly-Thoughts (CoAT)
1. **List "Criminal" Suspects**: Identify potential failure points (Infinite loops, Resource leaks, Race conditions, Null pointers, Logic errors, Edge cases).
2. **Negative Test Analysis**: simulate inputs that would break this code.
3. **Verdict**: Pass or Fail.

Return ONLY a JSON object with this structure:
{{
    "passed": boolean,
    "anomalies": ["List", "of", "specific", "bugs"],
    "bug_narrative": "A detailed explanation of WHY it failed, written to the developer to help them fix it.",
    "confidence": float (0.0-1.0)
}}
"""

    def _parse_verdict(self, response_text: str) -> DetectiveVerdict:
        """Parses the JSON response from the LLM."""
        import json
        import re
        
        # Clean up markdown code blocks if present
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response_text.strip()
            
        try:
            data = json.loads(json_str)
            return DetectiveVerdict(**data)
        except Exception:
            # Fallback for parsing errors
            return DetectiveVerdict(
                passed=False, 
                anomalies=["Parsing Error"], 
                bug_narrative="Failed to parse detective report.", 
                confidence=0.0
            )
