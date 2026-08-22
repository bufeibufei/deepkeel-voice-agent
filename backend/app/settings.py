from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ark_api_key: str = ""
    ark_model: str = "ark-code-latest"
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/plan/v3"
    speech_api_key: str = ""
    speech_asr_resource_id: str = "volc.seedasr.sauc.duration"
    speech_tts_resource_id: str = "seed-tts-2.0"
    speech_voice: str = "zh_female_vv_uranus_bigtts"
    voice_agent_demo_mode: bool = False
    voice_agent_host: str = "127.0.0.1"
    voice_agent_port: int = 8000

    @property
    def agent_live_enabled(self) -> bool:
        return bool(self.ark_api_key) and not self.voice_agent_demo_mode

    @property
    def speech_live_enabled(self) -> bool:
        return bool(self.speech_api_key) and not self.voice_agent_demo_mode

    @property
    def live_enabled(self) -> bool:
        return self.agent_live_enabled


@lru_cache
def get_settings() -> Settings:
    return Settings()
