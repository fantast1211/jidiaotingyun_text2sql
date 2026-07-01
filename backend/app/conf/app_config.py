import os
from dataclasses import dataclass, field
from pathlib import Path

from omegaconf import OmegaConf
from dotenv import load_dotenv

from app.conf.config_loader import load_config


# 日志配置
@dataclass
class File:
    enable: bool
    level: str
    path: str
    rotation: str
    retention: str


@dataclass
class Console:
    enable: bool
    level: str


@dataclass
class LoggingConfig:
    file: File
    console: Console


# 数据库配置
@dataclass
class DBConfig:
    host: str
    port: int
    user: str
    password: str
    database: str


@dataclass
class QdrantConfig:
    host: str
    port: int
    embedding_size: int


@dataclass
class EmbeddingConfig:
    base_url: str
    api_key: str
    model: str


@dataclass
class ESConfig:
    host: str
    port: int
    index_name: str


@dataclass
class LLMConfig:
    model_name: str
    api_key: str
    base_url: str


@dataclass
class SecurityConfig:
    allowed_statements: list[str] = field(default_factory=lambda: ["SELECT"])
    max_rows: int = 1000
    visible_tables: list[str] = field(default_factory=list)
    blocked_tables: list[str] = field(default_factory=list)


@dataclass
class UIConfig:
    confirm_before_execute: bool = True


@dataclass
class AppConfig:
    logging: LoggingConfig
    db_meta: DBConfig
    db_dw: DBConfig
    qdrant: QdrantConfig
    embedding: EmbeddingConfig
    es: ESConfig
    llm: LLMConfig
    security: SecurityConfig = field(default_factory=SecurityConfig)
    ui: UIConfig = field(default_factory=UIConfig)


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _apply_env_overrides(config: AppConfig) -> AppConfig:
    mappings = {
        "DB_META_HOST": ("db_meta", "host", str),
        "DB_META_PORT": ("db_meta", "port", int),
        "DB_META_USER": ("db_meta", "user", str),
        "DB_META_PASSWORD": ("db_meta", "password", str),
        "DB_META_DATABASE": ("db_meta", "database", str),
        "DB_DW_HOST": ("db_dw", "host", str),
        "DB_DW_PORT": ("db_dw", "port", int),
        "DB_DW_USER": ("db_dw", "user", str),
        "DB_DW_PASSWORD": ("db_dw", "password", str),
        "DB_DW_DATABASE": ("db_dw", "database", str),
        "QDRANT_HOST": ("qdrant", "host", str),
        "QDRANT_PORT": ("qdrant", "port", int),
        "QDRANT_EMBEDDING_SIZE": ("qdrant", "embedding_size", int),
        "EMBEDDING_BASE_URL": ("embedding", "base_url", str),
        "EMBEDDING_API_KEY": ("embedding", "api_key", str),
        "EMBEDDING_MODEL": ("embedding", "model", str),
        "ES_HOST": ("es", "host", str),
        "ES_PORT": ("es", "port", int),
        "ES_INDEX_NAME": ("es", "index_name", str),
        "LLM_MODEL_NAME": ("llm", "model_name", str),
        "LLM_API_KEY": ("llm", "api_key", str),
        "LLM_BASE_URL": ("llm", "base_url", str),
        "SECURITY_MAX_ROWS": ("security", "max_rows", int),
        "SECURITY_VISIBLE_TABLES": ("security", "visible_tables", _split_csv),
        "SECURITY_BLOCKED_TABLES": ("security", "blocked_tables", _split_csv),
    }

    for env_name, (section, field_name, caster) in mappings.items():
        raw_value = os.getenv(env_name)
        if raw_value is None:
            continue
        setattr(getattr(config, section), field_name, caster(raw_value))

    return config


config_file = Path(__file__).parents[2] / 'conf' / 'app_config.yaml'
env_file = Path(__file__).parents[3] / '.env'
load_dotenv(env_file)
context = OmegaConf.load(config_file)
schema = OmegaConf.structured(AppConfig)
app_config: AppConfig = OmegaConf.to_object(OmegaConf.merge(schema, context))
app_config = _apply_env_overrides(app_config)

if __name__ == '__main__':
    print(app_config.es.host)
