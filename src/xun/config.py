import os
import functools
from pathlib import Path
from dotenv import load_dotenv
import openai
from pydantic import BaseModel

from .types import ModelCapabilityType


ASSET_DIR = Path(__file__).parent / "assets"

class ConfigModel(BaseModel):
    ...

    def to_json(self) -> str:
        return self.model_dump_json(indent=4)
    
    @classmethod
    def from_json(cls, json_str: str) -> "ConfigModel":
        return cls.model_validate_json(json_str)
    
    def clone(self) -> "ConfigModel":
        return self.model_copy()

class ProviderConfig(ConfigModel):
    openai_base_url: str
    openai_api_key: str

    @classmethod
    def from_env(cls):
        openai_base_url = os.environ.get(f"{BRAND}_OPENAI_BASE_URL", 'http://localhost:8000/v1')
        openai_api_key = os.environ.get(f"{BRAND}_OPENAI_API_KEY", '')

        if not openai_base_url or not openai_api_key:
            raise RuntimeError(f"Missing OpenAI configuration. Please set {BRAND}_OPENAI_BASE_URL and {BRAND}_OPENAI_API_KEY environment variables.")

        return cls(
            openai_base_url=openai_base_url,
            openai_api_key=openai_api_key,
        )

class ModelConfig(ConfigModel):
    name: str
    capabilities: set[ModelCapabilityType]

    @classmethod
    def from_env(cls, provider_config: ProviderConfig):
        model_name = os.environ.get(f"{BRAND}_OPENAI_MODEL", '')
        capabilities = set(os.environ.get(f"{BRAND}_MODEL_CAPABILITIES", 'vision').split(','))

        if not model_name:
            # infer model name from the provider if not specified
            client = openai.OpenAI(base_url=provider_config.openai_base_url, api_key=provider_config.openai_api_key)
            models = client.models.list()
            if models and len(models.data) > 0:
                if not len(models.data) == 1:
                    print(f"Warning: Multiple models found in the provider, but no {BRAND}_OPENAI_MODEL specified. Defaulting to the first model.")
                model_name = models.data[0].id
            else:
                raise RuntimeError(f"Failed to infer OpenAI model from provider. Please specify a model using the {BRAND}_OPENAI_MODEL environment variable.")

        return cls(
            name=model_name,
            capabilities=capabilities,  # type: ignore
        )

class AgentConfig(ConfigModel):
    auto_confirm: bool
    provider: ProviderConfig
    model: ModelConfig

BRAND = "XUN"
@functools.lru_cache(maxsize=1)
def _app_config(_cache_id: str | None = None) -> AgentConfig:
    load_dotenv()

    def to_bool(value: str) -> bool:
        return value.lower() in {"true", "1", "yes", "y"}
    provider = ProviderConfig.from_env()
        
    return AgentConfig(
        auto_confirm = to_bool(os.environ.get(f"{BRAND}_AUTO_CONFIRM", "false")),
        provider = provider,
        model = ModelConfig.from_env(provider)
    )

def app_config(force_reload: bool = False) -> AgentConfig:
    ttl_hash = None
    if force_reload:
        ttl_hash = str(os.urandom(16))
    return _app_config(ttl_hash)