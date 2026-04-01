import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = str(DATA_DIR / "generated")
APP_HOST = os.getenv("SPORTS_AGENT_APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("SPORTS_AGENT_APP_PORT", "8765"))

LLM_PROVIDER = os.getenv("SPORTS_AGENT_LLM_PROVIDER", "template")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
