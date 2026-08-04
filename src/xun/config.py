import os
import functools
from dataclasses import dataclass
from dotenv import load_dotenv
import openai

from .types import ModelCapabilityType, ModelCapabilityOptions

@dataclass
class ProviderConfig:
    openai_base_url: str
    openai_api_key: str
    openai_model: str

    # Optional set of model capabilities
    model_capabilities: set[ModelCapabilityType]

    @classmethod
    def from_env(cls):
        openai_base_url = os.environ.get(f"{BRAND}_OPENAI_BASE_URL", 'http://localhost:8000/v1')
        openai_api_key = os.environ.get(f"{BRAND}_OPENAI_API_KEY", '')
        openai_model = os.environ.get(f"{BRAND}_OPENAI_MODEL", '')
        model_capabilities = set(os.environ.get(f"{BRAND}_MODEL_CAPABILITIES", 'vision').split(','))

        # infer model name from the provider if not specified
        if not openai_model:
            client = openai.OpenAI(base_url=openai_base_url, api_key=openai_api_key)
            models = client.models.list()
            if models and len(models.data) > 0:
                if not len(models.data) == 1:
                    print(f"Warning: Multiple models found in the provider, but no {BRAND}_OPENAI_MODEL specified. Defaulting to the first model.")
                openai_model = models.data[0].id
            else:
                raise RuntimeError(f"Failed to infer OpenAI model from provider. Please specify a model using the {BRAND}_OPENAI_MODEL environment variable.")

        for cap in model_capabilities:
            if cap not in ModelCapabilityOptions:
                raise ValueError(f"Invalid model capability: {cap}. Must be one of {ModelCapabilityOptions}")
        
        return cls(
            openai_base_url=openai_base_url,
            openai_api_key=openai_api_key,
            openai_model=openai_model,
            model_capabilities=model_capabilities   # type: ignore[assignment]
        )

@dataclass
class AppConfig:
    auto_confirm: bool
    auto_confirm_timeout: int
    provider: ProviderConfig

    def dict(self):
        def _to_dict(obj):
            if isinstance(obj, list):
                return [_to_dict(item) for item in obj]
            elif hasattr(obj, "__dataclass_fields__"):
                return {field: _to_dict(getattr(obj, field)) for field in obj.__dataclass_fields__}
            else:
                return obj
        return _to_dict(self)

BRAND = "XUN"
@functools.lru_cache(maxsize=1)
def _app_config(_cache_id: str | None = None) -> AppConfig:
    load_dotenv()

    def to_bool(value: str) -> bool:
        return value.lower() in {"true", "1", "yes", "y"}
    provider = ProviderConfig.from_env()
        
    return AppConfig(
        auto_confirm = to_bool(os.environ.get(f"{BRAND}_AUTO_CONFIRM", "false")),
        auto_confirm_timeout = int(os.environ.get(f"{BRAND}_AUTO_CONFIRM_TIMEOUT", "3")),
        provider = provider
    )

def app_config(force_reload: bool = False) -> AppConfig:
    ttl_hash = None
    if force_reload:
        ttl_hash = str(os.urandom(16))
    return _app_config(ttl_hash)