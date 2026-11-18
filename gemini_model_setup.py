"""Test a Gemini model with AssistantX's own GeminiProvider and save it if it works.

Run from C:\\AssistantX with the venv active:
    python gemini_model_setup.py                      # tests gemini-3.8-flash
    python gemini_model_setup.py gemini-3.5-flash-lite
"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

model = sys.argv[1] if len(sys.argv) > 1 else "gemini-3.8-flash"
print(f"Testing Gemini model: {model}\n")

from ai.gemini import GeminiProvider
from ai.provider import ChatMessage, Role

provider = GeminiProvider(model=model)

if not provider.is_available():
    print(provider.diagnostics())
    raise SystemExit("\nGemini is not available: 'google-genai' package or the API key is missing.")

result = provider.generate(
    [ChatMessage(Role.USER, "বাংলায় এক বাক্যে নিজের পরিচয় দাও।")],
    max_retries=1,
)

if not result.ok:
    print("FAILED:", result.error)
    low = str(result.error).lower()
    if "temperature" in low or "top_p" in low or "top_k" in low:
        print("\nHint: this model rejects the temperature/top_p setting. Send me this message.")
    elif "404" in low or "not_found" in low or "no longer available" in low:
        print("\nHint: this model name is not available to you. Try another one, e.g.:")
        print("  python gemini_model_setup.py gemini-3.5-flash-lite")
    raise SystemExit("\nNothing was saved.")

print("OK, answer:", result.text, "\n")

from config.settings import settings_manager as sm

try:
    sm.set("ai.gemini_model", model, save=True)
except TypeError:
    sm.set("ai.gemini_model", model)

print("Saved: ai.gemini_model =", sm.get("ai.gemini_model"))
print("Now run:  python main.py")
