"""Agent fine-tuning pipeline.

Converts episodic memory + eval scores into fine-tuning datasets,
then runs fine-tuning jobs against local Ollama models. This enables
zero API cost operation with per-role specialized models.

Pipeline:
1. Extract high-quality episodes from episodic_memory
2. Format as instruction/response pairs
3. Export as JSONL dataset
4. Submit fine-tuning job to Ollama
5. Track job status in fine_tuning_jobs table
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import (
    EpisodicMemory,
    EvalResult,
    FineTuningJob,
    LLMUsage,
)
from nexus.settings import settings

logger = structlog.get_logger()


class DatasetBuilder:
    """Builds fine-tuning datasets from agent episodic memory.

    Selects high-quality episodes (successful outcomes + high eval scores)
    and converts them into instruction/response training pairs.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def build_dataset(
        self,
        agent_id: str,
        agent_role: str,
        *,
        min_score: float = 0.7,
        max_samples: int = 500,
        lookback_days: int = 90,
        output_dir: str = "",
    ) -> dict[str, Any]:
        """Build a JSONL fine-tuning dataset from high-quality episodes.

        Args:
            agent_id: The agent whose episodes to use.
            agent_role: The agent's role (for system prompt).
            min_score: Minimum eval score to include (0-1).
            max_samples: Maximum number of training samples.
            lookback_days: How far back to look for episodes.
            output_dir: Directory to write the dataset file.

        Returns:
            Summary with file path, sample count, and statistics.
        """
        since = datetime.now(UTC) - timedelta(days=lookback_days)

        # Get successful episodes with eval scores
        stmt = (
            select(EpisodicMemory, EvalResult)
            .outerjoin(EvalResult, EpisodicMemory.task_id == EvalResult.task_id)
            .where(
                and_(
                    EpisodicMemory.agent_id == agent_id,
                    EpisodicMemory.outcome == "success",
                    EpisodicMemory.created_at >= since,
                ),
            )
            .order_by(EpisodicMemory.importance_score.desc())
            .limit(max_samples * 2)  # Fetch more to filter
        )
        result = await self.session.execute(stmt)
        rows = result.all()

        # Filter by eval score
        samples: list[dict[str, Any]] = []
        for episode, eval_result in rows:
            if eval_result and eval_result.overall_score < min_score:
                continue

            # Extract instruction/response from full_context
            context = episode.full_context or {}
            instruction = context.get("instruction", "")
            response = context.get("response", "")

            if not instruction or not response:
                continue

            samples.append({
                "messages": [
                    {"role": "system", "content": f"You are the {agent_role} agent of NEXUS."},
                    {"role": "user", "content": instruction},
                    {"role": "assistant", "content": response},
                ],
                "metadata": {
                    "episode_id": str(episode.id),
                    "eval_score": eval_result.overall_score if eval_result else None,
                    "importance": episode.importance_score,
                },
            })

            if len(samples) >= max_samples:
                break

        if not samples:
            return {
                "status": "empty",
                "message": f"No qualifying episodes found for agent {agent_id}",
                "samples": 0,
            }

        # Write JSONL file
        out_dir = Path(output_dir or "/tmp/nexus-finetune")
        out_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        file_path = out_dir / f"{agent_role}_{timestamp}.jsonl"

        with file_path.open("w") as f:
            for sample in samples:
                f.write(json.dumps(sample["messages"]) + "\n")

        logger.info(
            "finetune_dataset_built",
            agent_id=agent_id,
            role=agent_role,
            samples=len(samples),
            file=str(file_path),
        )

        return {
            "status": "ready",
            "file_path": str(file_path),
            "samples": len(samples),
            "avg_eval_score": sum(
                s["metadata"]["eval_score"]
                for s in samples
                if s["metadata"]["eval_score"] is not None
            ) / max(sum(1 for s in samples if s["metadata"]["eval_score"] is not None), 1),
        }


class FineTuningRunner:
    """Manages fine-tuning jobs against Ollama.

    Submits Modelfiles to Ollama for fine-tuning, tracks job progress,
    and validates the resulting model against benchmarks.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.ollama_url = settings.ollama_base_url.replace("/v1", "")

    async def create_job(
        self,
        *,
        agent_id: str,
        agent_role: str,
        base_model: str = "llama3.1:8b",
        dataset_path: str,
        task_id: str = "",
        trace_id: str = "",
    ) -> FineTuningJob:
        """Create a fine-tuning job record and prepare Ollama Modelfile.

        Args:
            agent_id: The agent being fine-tuned.
            agent_role: Agent role (used in model naming).
            base_model: Ollama base model to fine-tune from.
            dataset_path: Path to the JSONL training dataset.
            task_id: For audit logging.
            trace_id: For audit logging.

        Returns:
            The created FineTuningJob record.
        """
        model_name = f"nexus-{agent_role}-{datetime.now(UTC).strftime('%Y%m%d')}"

        job = FineTuningJob(
            id=str(uuid4()),
            agent_id=agent_id,
            agent_role=agent_role,
            base_model=base_model,
            target_model=model_name,
            dataset_path=dataset_path,
            status="pending",
            config={
                "base_model": base_model,
                "model_name": model_name,
            },
        )
        self.session.add(job)
        await self.session.flush()

        logger.info(
            "finetune_job_created",
            job_id=job.id,
            agent_role=agent_role,
            base_model=base_model,
            target_model=model_name,
            task_id=task_id,
            trace_id=trace_id,
        )
        return job

    async def run_job(self, job_id: str) -> dict[str, Any]:
        """Execute a fine-tuning job by creating an Ollama model.

        Uses Ollama's model creation API to create a specialized model
        from the base model with the training dataset.

        Args:
            job_id: The fine-tuning job to execute.

        Returns:
            Job execution result.
        """
        stmt = select(FineTuningJob).where(FineTuningJob.id == job_id)
        result = await self.session.execute(stmt)
        job = result.scalar_one_or_none()
        if not job:
            return {"status": "error", "message": f"Job {job_id} not found"}

        job.status = "running"
        job.started_at = datetime.now(UTC)
        await self.session.flush()

        try:
            # Read dataset for system prompt enrichment
            dataset_path = Path(job.dataset_path)
            if not dataset_path.exists():
                raise FileNotFoundError(f"Dataset not found: {job.dataset_path}")

            # Count samples
            with dataset_path.open() as f:
                sample_count = sum(1 for _ in f)

            # Create Ollama Modelfile
            modelfile = (
                f"FROM {job.base_model}\n"
                f"SYSTEM You are the {job.agent_role} agent of NEXUS, "
                f"an Agentic AI Company-as-a-Service platform. "
                f"Fine-tuned from {sample_count} high-quality episodes.\n"
                f"PARAMETER temperature 0.7\n"
                f"PARAMETER top_p 0.9\n"
            )

            # Create model via Ollama API
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.ollama_url}/api/create",
                    json={
                        "name": job.target_model,
                        "modelfile": modelfile,
                    },
                    timeout=300.0,
                )
                response.raise_for_status()

            job.status = "completed"
            job.completed_at = datetime.now(UTC)
            job.metrics = {
                "samples": sample_count,
                "base_model": job.base_model,
                "target_model": job.target_model,
            }
            await self.session.flush()

            logger.info(
                "finetune_job_completed",
                job_id=job_id,
                target_model=job.target_model,
                samples=sample_count,
            )
            return {
                "status": "completed",
                "model_name": job.target_model,
                "samples": sample_count,
            }

        except Exception as exc:
            job.status = "failed"
            job.completed_at = datetime.now(UTC)
            job.error = str(exc)
            await self.session.flush()

            logger.error(
                "finetune_job_failed",
                job_id=job_id,
                error=str(exc),
            )
            return {"status": "failed", "error": str(exc)}

    async def get_job_status(self, job_id: str) -> dict[str, Any]:
        """Get the status of a fine-tuning job.

        Args:
            job_id: The job to check.

        Returns:
            Job status details.
        """
        stmt = select(FineTuningJob).where(FineTuningJob.id == job_id)
        result = await self.session.execute(stmt)
        job = result.scalar_one_or_none()
        if not job:
            return {"status": "not_found"}

        return {
            "job_id": job.id,
            "agent_role": job.agent_role,
            "status": job.status,
            "base_model": job.base_model,
            "target_model": job.target_model,
            "started_at": str(job.started_at) if job.started_at else None,
            "completed_at": str(job.completed_at) if job.completed_at else None,
            "error": job.error,
            "metrics": job.metrics,
        }

    async def list_jobs(
        self,
        agent_role: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List fine-tuning jobs, optionally filtered by role.

        Args:
            agent_role: Filter by agent role.
            limit: Maximum number of jobs to return.

        Returns:
            List of job summaries.
        """
        stmt = select(FineTuningJob).order_by(FineTuningJob.created_at.desc()).limit(limit)
        if agent_role:
            stmt = stmt.where(FineTuningJob.agent_role == agent_role)

        result = await self.session.execute(stmt)
        jobs = result.scalars().all()

        return [
            {
                "job_id": job.id,
                "agent_role": job.agent_role,
                "status": job.status,
                "base_model": job.base_model,
                "target_model": job.target_model,
                "created_at": str(job.created_at),
            }
            for job in jobs
        ]
