"""Configuration schema and validation for XLMem experiments."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field, field_validator
import yaml


class ModelConfig(BaseModel):
    """Backbone LLM configuration."""

    name: str = Field(default="qwen2.5:7b-instruct")
    quantization: str = Field(default="q4_K_M")
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    backend: Literal["ollama", "vllm"] = Field(default="ollama")
    base_url: str = Field(default="http://localhost:11434")


class LanguageConfig(BaseModel):
    """Storage and probe language pairs."""

    store: Literal["en", "hi", "hi-en"] = Field(default="hi")
    probe: Literal["en", "hi", "hi-en"] = Field(default="en")


class BenchmarkConfig(BaseModel):
    """Benchmark dataset and session parameters."""

    fact_bank: str = Field(default="data/facts_v1.yaml")
    n_facts: int = Field(default=250, gt=0)
    filler_sessions: int = Field(default=3, ge=0)
    distractor_ratio: float = Field(default=0.3, ge=0.0, le=1.0)


class ExperimentConfig(BaseModel):
    """Root experiment configuration schema."""

    experiment: str
    framework: Literal["mem0", "letta", "amem", "mock"]
    model: ModelConfig = Field(default_factory=ModelConfig)
    embedder: str = Field(default="BAAI/bge-m3")
    languages: LanguageConfig = Field(default_factory=LanguageConfig)
    benchmark: BenchmarkConfig = Field(default_factory=BenchmarkConfig)
    mitigation: Literal["none", "normalize", "xling_er"] = Field(default="none")
    seeds: list[int] = Field(default_factory=lambda: [11, 22, 33])
    output_dir: str = Field(default="runs/experiment_default")

    @field_validator("seeds")
    @classmethod
    def validate_seeds(cls, v: list[int]) -> list[int]:
        if len(v) < 1:
            raise ValueError("At least one seed must be specified.")
        return v

    @classmethod
    def from_yaml(cls, path: str | Path) -> ExperimentConfig:
        """Load and validate configuration from a YAML file."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Config file not found at: {p}")
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls(**data)

    def to_yaml(self, path: str | Path) -> None:
        """Dump configuration to a YAML file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.model_dump(), f, sort_keys=False)
