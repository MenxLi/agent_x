import os
from dataclasses import dataclass
import subprocess

def get_docker_host_ip():
    result = subprocess.run("ip route | grep default | awk '{print $3}'", shell=True, capture_output=True, text=True)
    return result.stdout.strip()

@dataclass
class ProviderConfig:
    openai_base_url: str
    openai_api_key: str
    openai_model: str

@dataclass
class AppConfig:
    provider: ProviderConfig

def app_config():
    provider = ProviderConfig(
        openai_base_url = os.environ.get("AGENTX_OPENAI_BASE_URL", f"http://{get_docker_host_ip()}:8000/v1"),
        openai_api_key = os.environ.get("AGENTX_OPENAI_API_KEY", ""),
        openai_model = os.environ.get("AGENTX_OPENAI_MODEL", "/m/Qwen3.6-35B-A3B"),
    )
    return AppConfig(
        provider = provider
    )