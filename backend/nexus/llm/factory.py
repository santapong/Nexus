from __future__ import annotations

from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.gemini import GeminiModel

from nexus.db.models import AgentRole
from nexus.settings import settings

# Role -> model name mapping from settings
_AGENT_MODEL_MAP: dict[AgentRole, str] = {
    AgentRole.CEO: settings.model_ceo,
    AgentRole.ENGINEER: settings.model_engineer,
    AgentRole.ANALYST: settings.model_analyst,
    AgentRole.WRITER: settings.model_writer,
    AgentRole.QA: settings.model_qa,
    AgentRole.PROMPT_CREATOR: settings.model_prompt_creator,
}


class ModelFactory:
    """Creates Pydantic AI model instances based on agent role.

    No agent code references a specific provider directly.
    """

    @staticmethod
    def get_model(role: AgentRole, override: str | None = None) -> Model:
        """Get the appropriate LLM model for an agent role.

        Args:
            role: The agent's role determining which model to use.
            override: Optional model name to override the default.

        Returns:
            A Pydantic AI model instance.
        """
        model_name = override or _AGENT_MODEL_MAP[role]

        if model_name.startswith("claude"):
            return AnthropicModel(model_name, api_key=settings.anthropic_api_key)
        if model_name.startswith("gemini"):
            return GeminiModel(model_name, api_key=settings.google_api_key)

        msg = f"Unknown model: {model_name}"
        raise ValueError(msg)
