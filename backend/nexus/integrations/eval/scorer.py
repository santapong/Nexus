"""LLM-as-judge scorer — evaluates task output quality.

Uses a separate LLM call (Claude Haiku for cost efficiency) to judge
output quality across four dimensions: relevance, completeness,
accuracy, and formatting.
"""

from __future__ import annotations

import json

import structlog

from nexus.integrations.eval.schemas import EvalDimensions, EvalScoreResult

logger = structlog.get_logger()

_JUDGE_MODEL = "claude-haiku"

_JUDGE_PROMPT = """You are an expert evaluator. Score the AI agent output on four dimensions.
Each score must be a float between 0.0 and 1.0.

## Task instruction:
{instruction}

## Agent output:
{output}

## Scoring dimensions:
- relevance: How well does the output address the task instruction?
- completeness: Does the output cover all aspects of the request?
- accuracy: Is the information correct and well-reasoned?
- formatting: Is the output well-structured and readable?

Respond ONLY with valid JSON in this exact format:
{{
  "relevance": 0.0,
  "completeness": 0.0,
  "accuracy": 0.0,
  "formatting": 0.0,
  "reasoning": "Brief explanation of scores"
}}"""


async def score_output(
    *,
    task_id: str,
    instruction: str,
    output: str,
) -> EvalScoreResult:
    """Score a task output using LLM-as-judge.

    Args:
        task_id: The task being evaluated.
        instruction: The original task instruction.
        output: The agent's output to evaluate.

    Returns:
        EvalScoreResult with dimension scores and reasoning.
    """
    prompt = _JUDGE_PROMPT.format(
        instruction=instruction[:2000],
        output=output[:5000],
    )

    try:
        from nexus.core.llm.factory import ModelFactory

        model = ModelFactory.get_model_by_name(_JUDGE_MODEL)

        from pydantic_ai import Agent as PydanticAgent

        judge = PydanticAgent(model=model, system_prompt="You are an eval judge.")
        result = await judge.run(prompt)
        response_text = result.data

        # Parse JSON from response
        parsed = json.loads(response_text)
        dimensions = EvalDimensions(
            relevance=float(parsed.get("relevance", 0.5)),
            completeness=float(parsed.get("completeness", 0.5)),
            accuracy=float(parsed.get("accuracy", 0.5)),
            formatting=float(parsed.get("formatting", 0.5)),
        )
        overall = (
            dimensions.relevance
            + dimensions.completeness
            + dimensions.accuracy
            + dimensions.formatting
        ) / 4.0

        return EvalScoreResult(
            task_id=task_id,
            overall_score=round(overall, 3),
            dimensions=dimensions,
            judge_reasoning=parsed.get("reasoning", ""),
            judge_model=_JUDGE_MODEL,
        )

    except Exception as exc:
        logger.error("eval_scoring_failed", task_id=task_id, error=str(exc))
        # Return neutral scores on failure
        return EvalScoreResult(
            task_id=task_id,
            overall_score=0.5,
            dimensions=EvalDimensions(
                relevance=0.5,
                completeness=0.5,
                accuracy=0.5,
                formatting=0.5,
            ),
            judge_reasoning=f"Scoring failed: {exc}",
            judge_model=_JUDGE_MODEL,
        )
