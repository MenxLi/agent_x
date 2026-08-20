import os
import functools
from pathlib import Path
from dotenv import load_dotenv
import openai
from pydantic import BaseModel
from typing import Self
from string import Template

from .types import ModelCapabilityType


BRAND = "XUN"
ASSET_DIR = Path(__file__).parent / "assets"

def get_home_dir() -> Path:
    home_dir = os.environ.get(f"{BRAND}_HOME")
    if home_dir:
        return Path(home_dir)
    else:
        return Path.home() / f".{BRAND.lower()}"

class ConfigModel(BaseModel):

    def to_json(self) -> str:
        return self.model_dump_json(indent=4)
    
    @classmethod
    def from_json(cls, json_str: str) -> Self:
        return cls.model_validate_json(json_str)
    
    def clone(self) -> Self:
        return self.model_copy(deep=True)

class ProviderConfig(ConfigModel):
    openai_base_url: str
    openai_api_key: str


class ModelConfig(ConfigModel):
    name: str
    capabilities: set[ModelCapabilityType]

    def _assign_primary_model(self, client: openai.OpenAI) -> None:
        if not self.name:
            models = client.models.list()
            if models and len(models.data) > 0:
                self.name = models.data[0].id
                if not len(models.data) == 1:
                    print(f"Warning: Multiple models found in the provider, but no model name specified in the config. Defaulting to the first model: {self.name}.")
            else:
                raise RuntimeError(f"Failed to infer OpenAI model from provider. Please specify a model in the config.")

class AgentConfig(ConfigModel):
    auto_confirm: bool
    provider: ProviderConfig
    model: ModelConfig

def _default_config() -> AgentConfig:
    return AgentConfig(
        auto_confirm=False,
        provider=ProviderConfig(
            openai_base_url=r"${XUN_OPENAI_BASE_URL}",
            openai_api_key=r"${XUN_OPENAI_API_KEY}",
        ),
        model=ModelConfig(
            name="",
            capabilities={'vision'},
        ),
    )

@functools.lru_cache(maxsize=1)
def _load_config(_cache_id: str | None = None) -> AgentConfig:
    load_dotenv()
    home_dir = get_home_dir()
    config_path = home_dir / "config.json"

    def load_from_template(template_str: str) -> AgentConfig:
        template = Template(template_str)
        placeholders = template.get_identifiers()   # > python3.11
        env_vars = {}
        for placeholder in placeholders:
            if not placeholder.startswith(f"{BRAND}_"):
                raise RuntimeError(f"Invalid placeholder '{placeholder}' in config.json. All placeholders must start with '{BRAND}_'.")
            env_var_value = os.environ.get(placeholder)
            if env_var_value is None:
                raise RuntimeError(f"Missing environment variable for placeholder '{placeholder}' in config.json.")
            env_vars[placeholder] = env_var_value
        config_json = template.safe_substitute(env_vars)
        return AgentConfig.from_json(config_json)

    if config_path.exists():
        with open(config_path, "r") as f:
            config_json_template = f.read()
        return load_from_template(config_json_template)
    else:
        default_config = _default_config()
        home_dir.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w") as f:
            f.write(config_str:=default_config.to_json())
        return load_from_template(config_str)

def load_config(force_reload: bool = False) -> AgentConfig:
    """Load the global config (cached per-process).

    Serves as the default config source for new agents; individual agents
    may hold their own (cloned) config and should be read via `agent.config`.
    """
    cache_id = None
    if force_reload:
        cache_id = str(os.urandom(16))
    return _load_config(cache_id)