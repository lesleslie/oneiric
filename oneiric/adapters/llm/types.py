"""Shared LLM types for the Bodai ecosystem."""

from __future__ import annotations

from enum import StrEnum


class TaskType(StrEnum):
    """Task categories for model routing."""

    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    DEBUGGING = "debugging"
    REFACTORING = "refactoring"
    TESTING = "testing"
    REASONING = "reasoning"
    DOCUMENTATION = "documentation"
    ANALYSIS = "analysis"
    GENERAL = "general"
    SWARM = "swarm"
    QUICK = "quick"
    EMBEDDING = "embedding"
    CREATIVE = "creative"
    ML_INFERENCE = "ml_inference"
    AGENT_LOOP = "agent_loop"
    # Multimodal
    IMAGE_GENERATION = "image_generation"
    IMAGE_UNDERSTANDING = "image_understanding"
    AUDIO_SPEECH = "audio_speech"
    AUDIO_TRANSCRIPTION = "audio_transcription"
    VIDEO_GENERATION = "video_generation"
    # Deprecated — kept for one release cycle; callers should migrate to IMAGE_UNDERSTANDING
    VISION = "vision"
