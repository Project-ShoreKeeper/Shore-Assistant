"""
Pydantic models for all WebSocket message types.
Defines the contract between frontend and backend for both /ws/audio and /ws/chat endpoints.
"""

from pydantic import BaseModel
from typing import Optional, Literal
from enum import Enum


# ==================== Enums ====================

class ServerMessageType(str, Enum):
    TRANSCRIPT = "transcript"
    AGENT_ACTION = "agent_action"
    LLM_TOKEN = "llm_token"
    LLM_COMPLETE = "llm_complete"
    TTS_START = "tts_start"
    TTS_END = "tts_end"
    STATUS = "status"
    ERROR = "error"
    NOTIFICATION = "notification"


class AgentActionType(str, Enum):
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    VISION_SWAP = "vision_swap"


# ==================== Client -> Server ====================

class UserMessage(BaseModel):
    type: Literal["user_message"] = "user_message"
    text: str
    source: Literal["voice", "keyboard"] = "keyboard"


class ConfigMessage(BaseModel):
    type: Literal["config"] = "config"
    data: dict


class CancelMessage(BaseModel):
    type: Literal["cancel"] = "cancel"


# ==================== Server -> Client ====================

class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str


class TranscriptData(BaseModel):
    duration: Optional[float] = None
    processing_time: Optional[float] = None
    language: Optional[str] = None
    language_prob: Optional[float] = None
    segments: Optional[list[TranscriptSegment]] = None
    skipped: Optional[bool] = None
    reason: Optional[str] = None


class TranscriptMessage(BaseModel):
    type: Literal["transcript"] = "transcript"
    text: str
    isFinal: bool = True
    data: Optional[TranscriptData] = None


class AgentActionMessage(BaseModel):
    type: Literal["agent_action"] = "agent_action"
    action: AgentActionType
    detail: str
    tool: Optional[str] = None
    args: Optional[dict] = None
    result: Optional[str] = None
    timestamp: float


class LLMTokenMessage(BaseModel):
    type: Literal["llm_token"] = "llm_token"
    token: str
    accumulated: str


class LLMCompleteMessage(BaseModel):
    type: Literal["llm_complete"] = "llm_complete"
    text: str


class TTSStartMessage(BaseModel):
    type: Literal["tts_start"] = "tts_start"
    sample_rate: int = 22050
    format: str = "pcm_s16le"


class TTSEndMessage(BaseModel):
    type: Literal["tts_end"] = "tts_end"


class StatusMessage(BaseModel):
    type: Literal["status"] = "status"
    message: str


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    message: str


class NotificationMessage(BaseModel):
    type: Literal["notification"] = "notification"
    task_id: str
    task_type: str
    message: str
    timestamp: float
