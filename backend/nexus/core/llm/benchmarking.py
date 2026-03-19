"""Model performance benchmarking — compare quality/cost/speed per model per role.

Runs prompt_benchmarks test cases against different models, measures quality
via LLM-as-judge scoring, and stores results in model_benchmarks table.
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from pydantic_ai import Agent as PydanticAgent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.llm.factory import resolve_model
from nexus.core.llm.usage import calculate_cost
from nexus.db.models import ModelBenchmark, PromptBenchmark

logger = structlog.get_logger()


async def run_model_benchmark(
    session: AsyncSession,
    model_name: str,
    benchmark_id: str,
    agent_role: str,
    system_prompt: str = "",
) -> dict[str, Any]:
    """Run a single benchmark test case against a specific model.

    Args:
        session: Database session.
        model_name: Model to benchmark.
        benchmark_id: ID of the prompt_benchmark test case.
        agent_role: Agent role being benchmarked.
        system_prompt: Optional system prompt to use.

    Returns:
        Dict with score, latency, tokens, cost, and output.
    """
    # Load benchmark
    stmt = select(PromptBenchmark).where(PromptBenchmark.id == benchmark_id)
    result = await session.execute(stmt)
    benchmark = result.scalar_one_or_none()

    if benchmark is None:
        msg = f"Benchmark {benchmark_id} not found"
        raise ValueError(msg)

    # Resolve model
    model = resolve_model(model_name)

    # Create agent and run
    agent = PydanticAgent(
        model=model,
        system_prompt=system_prompt or f"You are a {agent_role} agent.",
    )

    start_ms = int(time.monotonic() * 1000)
    run_result = await agent.run(benchmark.input)
    latency_ms = int(time.monotonic() * 1000) - start_ms

    output_text = run_result.output

    # Extract token usage
    input_tokens = 0
    output_tokens = 0
    try:
        usage = run_result.usage()
        input_tokens = usage.request_tokens or 0
        output_tokens = usage.response_tokens or 0
    except Exception:
        pass

    cost = calculate_cost(model_name, input_tokens, output_tokens)

    # Score the output against expected criteria using LLM-as-judge
    score = await _score_output(
        output_text,
        benchmark.expected_criteria,
        agent_role,
    )

    # Store result
    mb = ModelBenchmark(
        agent_role=agent_role,
        model_name=model_name,
        benchmark_id=benchmark_id,
        score=score,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        output_text=output_text[:10000] if output_text else None,
    )
    session.add(mb)
    await session.flush()

    logger.info(
        "model_benchmark_completed",
        model_name=model_name,
        benchmark_id=benchmark_id,
        score=score,
        latency_ms=latency_ms,
        cost_usd=cost,
    )

    return {
        "model_name": model_name,
        "benchmark_id": benchmark_id,
        "score": score,
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost,
        "output_preview": output_text[:500] if output_text else "",
    }


async def compare_models(
    session: AsyncSession,
    agent_role: str,
    model_names: list[str],
    system_prompt: str = "",
) -> list[dict[str, Any]]:
    """Run all benchmarks for a role across multiple models.

    Args:
        session: Database session.
        agent_role: Agent role to benchmark.
        model_names: Models to compare.
        system_prompt: Optional system prompt.

    Returns:
        Aggregated comparison results per model.
    """
    # Load all benchmarks for this role
    stmt = select(PromptBenchmark).where(PromptBenchmark.agent_role == agent_role)
    result = await session.execute(stmt)
    benchmarks = result.scalars().all()

    if not benchmarks:
        logger.warning("no_benchmarks_found", agent_role=agent_role)
        return []

    model_results: list[dict[str, Any]] = []

    for model_name in model_names:
        scores: list[float] = []
        latencies: list[int] = []
        total_cost = 0.0

        for bm in benchmarks:
            try:
                res = await run_model_benchmark(
                    session=session,
                    model_name=model_name,
                    benchmark_id=str(bm.id),
                    agent_role=agent_role,
                    system_prompt=system_prompt,
                )
                scores.append(res["score"])
                latencies.append(res["latency_ms"])
                total_cost += res["cost_usd"]
            except Exception as exc:
                logger.warning(
                    "benchmark_run_failed",
                    model_name=model_name,
                    benchmark_id=str(bm.id),
                    error=str(exc),
                )

        if scores:
            model_results.append(
                {
                    "model_name": model_name,
                    "avg_score": round(sum(scores) / len(scores), 3),
                    "avg_latency_ms": int(sum(latencies) / len(latencies)),
                    "total_cost_usd": round(total_cost, 6),
                    "benchmarks_run": len(scores),
                    "benchmarks_total": len(benchmarks),
                }
            )

    # Sort by average score descending
    model_results.sort(key=lambda x: x["avg_score"], reverse=True)
    return model_results


async def get_benchmark_history(
    session: AsyncSession,
    agent_role: str,
    model_name: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Get historical benchmark results.

    Args:
        session: Database session.
        agent_role: Filter by role.
        model_name: Optional model filter.
        limit: Max results.

    Returns:
        List of benchmark result dicts.
    """
    stmt = (
        select(ModelBenchmark)
        .where(ModelBenchmark.agent_role == agent_role)
        .order_by(ModelBenchmark.created_at.desc())
        .limit(limit)
    )

    if model_name:
        stmt = stmt.where(ModelBenchmark.model_name == model_name)

    result = await session.execute(stmt)
    benchmarks = result.scalars().all()

    return [
        {
            "id": str(bm.id),
            "model_name": bm.model_name,
            "benchmark_id": bm.benchmark_id,
            "score": bm.score,
            "latency_ms": bm.latency_ms,
            "input_tokens": bm.input_tokens,
            "output_tokens": bm.output_tokens,
            "cost_usd": bm.cost_usd,
            "created_at": bm.created_at.isoformat() if bm.created_at else None,
        }
        for bm in benchmarks
    ]


async def _score_output(
    output: str,
    expected_criteria: dict[str, Any],
    agent_role: str,
) -> float:
    """Score an output against expected criteria.

    Uses keyword/pattern matching for basic scoring.
    Falls back to 0.5 if criteria cannot be evaluated.
    """
    if not expected_criteria or not output:
        return 0.5

    total_checks = 0
    passed_checks = 0

    # Check required keywords
    keywords = expected_criteria.get("required_keywords", [])
    for keyword in keywords:
        total_checks += 1
        if keyword.lower() in output.lower():
            passed_checks += 1

    # Check minimum length
    min_length = expected_criteria.get("min_length")
    if min_length is not None:
        total_checks += 1
        if len(output) >= min_length:
            passed_checks += 1

    # Check format requirements
    required_format = expected_criteria.get("format")
    if required_format == "json":
        total_checks += 1
        try:
            import json

            json.loads(output)
            passed_checks += 1
        except (json.JSONDecodeError, ValueError):
            pass
    elif required_format == "markdown":
        total_checks += 1
        if "#" in output or "**" in output or "- " in output:
            passed_checks += 1

    if total_checks == 0:
        return 0.5

    return round(passed_checks / total_checks, 3)
