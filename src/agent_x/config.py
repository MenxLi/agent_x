import os
from dataclasses import dataclass
import subprocess
import functools
import sys
import time
import threading
from selectors import DefaultSelector, EVENT_READ

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

BRAND = "AGENTX"
@functools.lru_cache(maxsize=1)
def app_config():
    def to_bool(value: str) -> bool:
        return value.lower() in {"true", "1", "yes", "y"}
    provider = ProviderConfig(
        openai_base_url = os.environ.get(f"{BRAND}_OPENAI_BASE_URL", f"http://{get_docker_host_ip()}:8000/v1"),
        openai_api_key = os.environ.get(f"{BRAND}_OPENAI_API_KEY", ""),
        openai_model = os.environ.get(f"{BRAND}_OPENAI_MODEL", "/m/Qwen3.6-35B-A3B"),
    )
    return AppConfig(
        auto_confirm = to_bool(os.environ.get(f"{BRAND}_AUTO_CONFIRM", "false")),
        auto_confirm_timeout = int(os.environ.get(f"{BRAND}_AUTO_CONFIRM_TIMEOUT", "3")),
        provider = provider
    )


def _confirm(prompt: str, default: bool = False) -> bool:
    from rich.prompt import Confirm
    from rich.console import Console

    cfg = app_config()
    if not cfg.auto_confirm:
        return Confirm.ask(prompt, default=default)
    else:
        console = Console()
        if cfg.auto_confirm_timeout <= 0 or not sys.stdin.isatty():
            return default

        def parse_confirmation(response: str) -> bool | None:
            normalized = response.strip().lower()
            if normalized == "":
                return default
            if normalized in {"y", "yes"}:
                return True
            if normalized in {"n", "no"}:
                return False
            return None

        selector = DefaultSelector()
        try:
            selector.register(sys.stdin, EVENT_READ)
        except (ValueError, OSError, PermissionError):
            return default

        deadline = time.monotonic() + cfg.auto_confirm_timeout
        suffix = "[Y/n]" if default else "[y/N]"
        try:
            while True:
                remaining = deadline - time.monotonic() + 0.01
                if remaining <= 0:
                    console.print()
                    return default

                console.print(
                    f"{prompt} {suffix} (auto-confirming in {max(1, int(remaining))} seconds): ",
                    end="",
                    markup=False,
                    soft_wrap=True,
                )
                if not selector.select(remaining):
                    console.print()
                    return default

                response = sys.stdin.readline()
                if response == "":
                    console.print()
                    return default

                approved = parse_confirmation(response)
                if approved is not None:
                    return approved

                console.print("[prompt.invalid]Please enter Y or N[/prompt.invalid]")
        finally:
            selector.close()

_confirm_lock = threading.Lock()
def confirm(prompt: str, default: bool = False) -> bool:
    with _confirm_lock:
        return _confirm(prompt, default)