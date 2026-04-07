import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
NPS_API_KEY = os.getenv("NPS_API_KEY")

MODEL = "claude-sonnet-4-20250514"
