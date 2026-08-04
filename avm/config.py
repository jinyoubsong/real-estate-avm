import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    data_go_kr_api_key: str
    vworld_api_key: str
    ecos_api_key: str
    db_path: Path


def load_settings() -> Settings:
    return Settings(
        data_go_kr_api_key=os.environ.get("DATA_GO_KR_API_KEY", ""),
        vworld_api_key=os.environ.get("VWORLD_API_KEY", ""),
        ecos_api_key=os.environ.get("ECOS_API_KEY", ""),
        db_path=PROJECT_ROOT / os.environ.get("AVM_DB_PATH", "data/avm.db"),
    )
