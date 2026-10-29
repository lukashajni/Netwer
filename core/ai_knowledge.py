# The instructions live in core/ai_prompts.py, which is git ignored.
# Without it Netwer falls back to the short public stand-in.
try:
    from core.ai_prompts import APP_GUIDE, SYSTEM_PROMPT
except ImportError:
    from core.ai_prompts_example import APP_GUIDE, SYSTEM_PROMPT


def build_system_prompt() -> str:
    guide = "\n".join(f"- {t}: {d}" for t, d in APP_GUIDE)
    return SYSTEM_PROMPT.format(guide=guide)
