"""Data models for jobs and configuration."""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class JobState(str, Enum):
    """Job lifecycle states."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD = "dead"


class Job(BaseModel):
    """Job specification."""
    id: str
    command: str
    state: JobState = JobState.PENDING
    attempts: int = 0
    max_retries: int = 3
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    next_retry_at: Optional[datetime] = None
    error_message: Optional[str] = None

    class Config:
        use_enum_values = False


class Config(BaseModel):
    """System configuration."""
    max_retries: int = 3
    backoff_base: float = 2.0  # exponential backoff base
    backoff_max_delay: int = 3600  # max delay in seconds (1 hour)

    class Config:
        use_enum_values = False
