"""
Flux 중앙 집중식 설정 모듈

모든 설정값을 단일 모듈로 통합합니다.
우선순위: 환경변수 > config.json > 기본값

사용법:
    from flux.config import get_config
    cfg = get_config()
    print(cfg.max_tool_rounds)  # 10

agent.yaml 로드:
    from flux.config import load_agent_config, AgentConfig
    data = load_agent_config("agent.yaml")
    agent = AgentConfig(**data)
"""

import os
import json
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Agent YAML Config (pydantic)
# ---------------------------------------------------------------------------

class BudgetConfig(BaseModel):
    """에이전트 예산 설정"""
    per_run: float = 0.10
    daily: float = 1.00
    monthly: float = 10.00


class AgentConfig(BaseModel):
    """agent.yaml 검증용 pydantic 모델"""
    name: str
    description: str = ""
    schedule: Optional[str] = None
    model: str = "claude-haiku"
    max_tokens: int = 4096
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    tools: list[str] = Field(default_factory=list)
    system_prompt: str = ""
    user_prompt: str = ""


def load_agent_config(yaml_path: str) -> dict:
    """Load and validate agent configuration from YAML file.

    Args:
        yaml_path: agent.yaml 파일 경로

    Returns:
        파싱된 딕셔너리 (AgentConfig로 검증 가능)

    Raises:
        FileNotFoundError: 파일이 없을 때
        yaml.YAMLError: YAML 파싱 실패 시
    """
    import yaml
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"agent.yaml must be a mapping, got {type(data).__name__}")
    return data


# ---------------------------------------------------------------------------
# Runtime Config (dataclass)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Config:
    """중앙 집중식 설정 (불변 객체)"""

    # LLM 설정
    default_model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 4096
    max_tool_rounds: int = 10
    max_daily_calls: int = 100
    max_history: int = 50

    # 복원력 설정
    llm_retry_count: int = 3
    llm_retry_base_delay: float = 1.0
    llm_retry_max_delay: float = 16.0
    tool_timeout_seconds: float = 30.0

    # 메시지 제한
    max_message_length: int = 10000

    # 데몬 설정
    daemon_max_restarts: int = 5
    daemon_restart_delay: int = 5

    # 로깅
    log_level: str = "INFO"
    log_format: str = "text"           # "text" | "json"
    log_file: str = "logs/flux.log"
    log_max_bytes: int = 10_485_760    # 10MB
    log_backup_count: int = 5

    # 스트리밍
    streaming_enabled: bool = True

    # 예산
    weekly_budget_usd: float = 10.0
    max_weekly_calls: int = 700

    # 기타
    backup_dir: str = "backups"
    api_version: str = "v1"


def _str_to_bool(s: str) -> bool:
    """문자열을 bool로 변환"""
    return s.lower() in ("true", "1", "yes")


# 환경변수 매핑 (ENV_NAME -> (field_name, type_converter))
_ENV_MAP = {
    "LLM_MODEL": ("default_model", str),
    "MAX_TOKENS": ("max_tokens", int),
    "MAX_TOOL_ROUNDS": ("max_tool_rounds", int),
    "MAX_DAILY_CALLS": ("max_daily_calls", int),
    "MAX_HISTORY": ("max_history", int),
    "LLM_RETRY_COUNT": ("llm_retry_count", int),
    "LLM_RETRY_BASE_DELAY": ("llm_retry_base_delay", float),
    "TOOL_TIMEOUT": ("tool_timeout_seconds", float),
    "DAEMON_MAX_RESTARTS": ("daemon_max_restarts", int),
    "DAEMON_RESTART_DELAY": ("daemon_restart_delay", int),
    "LOG_LEVEL": ("log_level", str),
    "LOG_FORMAT": ("log_format", str),
    "LOG_FILE": ("log_file", str),
    "LOG_MAX_BYTES": ("log_max_bytes", int),
    "LOG_BACKUP_COUNT": ("log_backup_count", int),
    "STREAMING_ENABLED": ("streaming_enabled", _str_to_bool),
    "WEEKLY_BUDGET_USD": ("weekly_budget_usd", float),
    "MAX_WEEKLY_CALLS": ("max_weekly_calls", int),
    "BACKUP_DIR": ("backup_dir", str),
}


# 설정 필드 범위 제한
_FIELD_BOUNDS = {
    "max_tool_rounds": (1, 50),
    "llm_retry_count": (0, 10),
    "llm_retry_base_delay": (0.1, 60.0),
    "llm_retry_max_delay": (1.0, 300.0),
    "tool_timeout_seconds": (1.0, 300.0),
    "max_history": (2, 500),
    "max_daily_calls": (1, 100000),
    "max_tokens": (100, 32000),
    "max_message_length": (100, 100000),
    "weekly_budget_usd": (0.01, 10000.0),
    "max_weekly_calls": (1, 100000),
}


def _clamp(field_name, value):
    """설정값의 범위를 제한"""
    if field_name in _FIELD_BOUNDS:
        lo, hi = _FIELD_BOUNDS[field_name]
        return type(value)(max(lo, min(hi, value)))
    return value


def _load_config_file(path: str = "config.json") -> dict:
    """config.json 로드 (없으면 빈 dict 반환)"""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def load_config(config_path: str = "config.json") -> Config:
    """설정 로드 (환경변수 > config.json > 기본값)"""
    file_config = _load_config_file(config_path)
    overrides = {}

    for env_name, (field_name, converter) in _ENV_MAP.items():
        # 1. 환경변수 확인
        env_val = os.environ.get(env_name)
        if env_val is not None:
            try:
                overrides[field_name] = _clamp(field_name, converter(env_val))
            except (ValueError, TypeError):
                pass  # 변환 실패 시 무시
            continue

        # 2. config.json 확인
        if field_name in file_config:
            try:
                overrides[field_name] = _clamp(field_name, converter(file_config[field_name]))
            except (ValueError, TypeError):
                pass

    return Config(**overrides)


# 싱글턴 캐시
_cached_config: Optional[Config] = None


def get_config(config_path: str = "config.json") -> Config:
    """설정 싱글턴 반환 (최초 호출 시 로드)"""
    global _cached_config
    if _cached_config is None:
        _cached_config = load_config(config_path)
    return _cached_config


def reset_config() -> None:
    """설정 캐시 초기화 (테스트용)"""
    global _cached_config
    _cached_config = None
