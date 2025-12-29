"""Kimi-K2 LLM integration for SHAIL."""

import logging
from typing import Dict, Any, Optional, List
import httpx

logger = logging.getLogger(__name__)


class KimiK2Client:
    """
    Client for Kimi-K2 LLM API.
    
    Kimi-K2 will serve as the master LLM for SHAIL's orchestration.
    """
    
    def __init__(self, api_key: Optional[str] = None, base_url: str = "https://api.moonshot.cn/v1"):
        """
        Initialize the Kimi-K2 client.
        
        Args:
            api_key: Kimi-K2 API key
            base_url: API base URL
        """
        self.api_key = api_key
        self.base_url = base_url
        self.model = "moonshot-v1-8k"  # Kimi-K2 model name
        logger.info("Initialized KimiK2Client")
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Send a chat completion request to Kimi-K2.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content'
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            
        Returns:
            Dictionary with response
        """
        if not self.api_key:
            return {
                "error": "Kimi-K2 API key not configured",
            }
        
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        
        if max_tokens:
            payload["max_tokens"] = max_tokens
        
        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=60)
            response.raise_for_status()
            
            result = response.json()
            
            return {
                "success": True,
                "content": result["choices"][0]["message"]["content"],
                "usage": result.get("usage", {}),
            }
        
        except Exception as e:
            logger.error(f"Kimi-K2 API error: {e}")
            return {
                "success": False,
                "error": str(e),
            }
    
    def get_capabilities(self) -> Dict[str, Any]:
        """
        Get client capabilities.
        
        Returns:
            Dictionary describing capabilities
        """
        return {
            "name": "kimi_k2",
            "model": self.model,
            "role": "master",
            "capabilities": ["chat", "orchestration"],
        }
