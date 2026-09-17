"""Single chokepoint for ALL LLM model calls in XLMem.

Hard Rules:
1. No paid APIs (OpenAI, Anthropic, Gemini, Cohere). Local open models only.
2. Every LLM call across the repository must route through this client.
3. Seeding, temperature, logging, and token accounting are centralized here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import time
from typing import Any
import requests

logger = logging.getLogger(__name__)

FORBIDDEN_PROVIDERS = [
    "openai",
    "anthropic",
    "cohere",
    "gemini",
    "groq",
    "together",
    "fireworks",
    "deepseek",
]


@dataclass
class LLMResponse:
    """Standardized response from the LLM client."""

    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMCallLog:
    """Trace log of a single LLM invocation."""

    timestamp: float
    model: str
    prompt: str
    response: str
    temperature: float
    seed: int
    prompt_tokens: int
    completion_tokens: int
    latency_seconds: float
    extra: dict[str, Any] = field(default_factory=dict)


class LLMClient:
    """Unified client for local open-weight inference.

    Routes to local Ollama or vLLM instances. Prohibits paid cloud APIs.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        backend: str = "ollama",
        default_model: str = "qwen2.5:7b-instruct",
        mock_mode: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.backend = backend.lower()
        self.default_model = default_model
        self.mock_mode = mock_mode
        self._history: list[LLMCallLog] = []

        # Enforce Hard Rule 1: No paid APIs
        self._validate_no_paid_apis(self.base_url)

    @staticmethod
    def _validate_no_paid_apis(url: str) -> None:
        lowered = url.lower()
        for forbidden in FORBIDDEN_PROVIDERS:
            if forbidden in lowered:
                raise ValueError(
                    f"VIOLATION OF HARD RULE 1: Paid/cloud API detected ('{forbidden}' in '{url}'). "
                    "XLMem is zero-cost and strictly restricted to local open-weight models."
                )

    def generate(
        self,
        prompt: str,
        model: str | None = None,
        temperature: float = 0.0,
        seed: int = 42,
        max_tokens: int = 512,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Issue a completion request to the local model backend.

        Args:
            prompt: User prompt text.
            model: Model name/tag.
            temperature: Sampling temperature (default 0.0 for deterministic evaluation).
            seed: Seed for reproducibility.
            max_tokens: Max tokens to generate.
            system_prompt: Optional system instruction.
            **kwargs: Extra parameters passed to the backend.

        Returns:
            LLMResponse containing the generated text and token metrics.
        """
        active_model = model or self.default_model
        start_time = time.time()

        if self.mock_mode:
            # Deterministic mock response for offline testing
            resp_text = f"[MOCK_RESPONSE to: {prompt[:30]}...]"
            prompt_tokens = len(prompt.split())
            completion_tokens = len(resp_text.split())
            latency = time.time() - start_time
            response = LLMResponse(
                text=resp_text,
                model=active_model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                latency_seconds=latency,
            )
            self._record_log(
                active_model,
                prompt,
                resp_text,
                temperature,
                seed,
                prompt_tokens,
                completion_tokens,
                latency,
            )
            return response

        if self.backend == "ollama":
            response = self._call_ollama(
                prompt=prompt,
                model=active_model,
                temperature=temperature,
                seed=seed,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
                **kwargs,
            )
        elif self.backend == "vllm":
            response = self._call_vllm(
                prompt=prompt,
                model=active_model,
                temperature=temperature,
                seed=seed,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
                **kwargs,
            )
        else:
            raise ValueError(f"Unsupported backend '{self.backend}'. Must be 'ollama' or 'vllm'.")

        self._record_log(
            active_model,
            prompt,
            response.text,
            temperature,
            seed,
            response.prompt_tokens,
            response.completion_tokens,
            response.latency_seconds,
        )
        return response

    def _call_ollama(
        self,
        prompt: str,
        model: str,
        temperature: float,
        seed: int,
        max_tokens: int,
        system_prompt: str | None,
        **kwargs: Any,
    ) -> LLMResponse:
        endpoint = f"{self.base_url}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "seed": seed,
                "num_predict": max_tokens,
            },
        }
        if system_prompt:
            payload["system"] = system_prompt

        start = time.time()
        try:
            res = requests.post(endpoint, json=payload, timeout=60)
            res.raise_for_status()
            data = res.json()
        except requests.RequestException as e:
            logger.error("Failed to connect to Ollama at %s: %s", endpoint, e)
            raise ConnectionError(f"Ollama connection error at {endpoint}: {e}") from e

        latency = time.time() - start
        response_text = data.get("response", "")
        prompt_eval_count = data.get("prompt_eval_count", 0)
        eval_count = data.get("eval_count", 0)

        return LLMResponse(
            text=response_text,
            model=model,
            prompt_tokens=prompt_eval_count,
            completion_tokens=eval_count,
            total_tokens=prompt_eval_count + eval_count,
            latency_seconds=latency,
            metadata={"done_reason": data.get("done_reason")},
        )

    def _call_vllm(
        self,
        prompt: str,
        model: str,
        temperature: float,
        seed: int,
        max_tokens: int,
        system_prompt: str | None,
        **kwargs: Any,
    ) -> LLMResponse:
        endpoint = f"{self.base_url}/chat/completions"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "seed": seed,
            "max_tokens": max_tokens,
        }

        start = time.time()
        try:
            res = requests.post(endpoint, json=payload, timeout=60)
            res.raise_for_status()
            data = res.json()
        except requests.RequestException as e:
            logger.error("Failed to connect to vLLM at %s: %s", endpoint, e)
            raise ConnectionError(f"vLLM connection error at {endpoint}: {e}") from e

        latency = time.time() - start
        choice = data["choices"][0]
        response_text = choice["message"]["content"]
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)

        return LLMResponse(
            text=response_text,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            latency_seconds=latency,
            metadata={"finish_reason": choice.get("finish_reason")},
        )

    def _record_log(
        self,
        model: str,
        prompt: str,
        response: str,
        temperature: float,
        seed: int,
        prompt_tokens: int,
        completion_tokens: int,
        latency: float,
    ) -> None:
        self._history.append(
            LLMCallLog(
                timestamp=time.time(),
                model=model,
                prompt=prompt,
                response=response,
                temperature=temperature,
                seed=seed,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_seconds=latency,
            )
        )

    def get_history(self) -> list[LLMCallLog]:
        """Return a copy of the invocation trace history."""
        return list(self._history)

    def total_tokens_used(self) -> int:
        """Return total cumulative tokens consumed."""
        return sum(log.prompt_tokens + log.completion_tokens for log in self._history)


# Global singleton client instance initialized on demand
_GLOBAL_CLIENT: LLMClient | None = None


def get_llm_client(**kwargs: Any) -> LLMClient:
    """Obtain or initialize the global LLMClient."""
    global _GLOBAL_CLIENT
    if _GLOBAL_CLIENT is None or kwargs:
        _GLOBAL_CLIENT = LLMClient(**kwargs)
    return _GLOBAL_CLIENT
