# services/__init__.py
from .ai_assistant import MultiProjectAIAssistant
from .web_ui import MultiProjectAIChatbotWebUI

__all__ = [
    'MultiProjectAIAssistant',
    'MultiProjectAIChatbotWebUI'
]