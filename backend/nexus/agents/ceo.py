"""CEO Agent — full task decomposer and orchestrator (Phase 7).

The CEO receives tasks from task.queue (human) and a2a.inbound (external).
For complex tasks, it follows a 5-phase human-like company workflow:

  Phase 1: Requirements extraction (CEO + Analyst)
  Phase 2: Conference room discussion (relevant agents debate approach)
  Phase 3: User approval gate (plan presented for approval)
  Phase 4: Execution (decompose → dispatch → aggregate → Director → QA)
  Phase 5: Post-execution evaluation (agents reconvene to check output)

Simple tasks skip directly to Phase 4 (existing decomposition flow).

Also subscribes to agent.responses to track subtask completion,
plan.approval for user approval responses, and meeting.room for
conference room coordination.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from uuid import UUID, uuid4

import structlog
from pydantic_ai import Agent as PydanticAgent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.agents.base import AgentBase
from nexus.core.kafka.meeting import (
    MeetingConfig,
    MeetingRoom,
    close_meeting,
    create_meeting,
    get_meeting,
    save_meeting,
)
from nexus.core.kafka.producer import publish
from nexus.core.kafka.schemas import AgentCommand, AgentResponse, KafkaMessage
from nexus.core.kafka.topics import Topics
from nexus.core.llm.usage import calculate_cost, record_usage
from nexus.db.models import AgentRole, HumanApproval, ApprovalStatus, Task, TaskStatus
from nexus.memory.episodic import write_episode
from nexus.memory.working import get_working_memory, set_working_memory

logger = structlog.get_logger()

_MAX_RETRIES = 5
_RETRY_BACKOFF_SECONDS = [5.0, 10.0, 20.0, 30.0, 45.0]

# Valid specialist roles the CEO can delegate to
_DELEGATABLE_ROLES = {"engineer", "analyst", "writer"}

# Keywords suggesting a complex task that warrants a conference room meeting
_COMPLEXITY_KEYWORDS = re.compile(
    r"\b(build|design|architect|integrate|migrate|implement|create|develop|"
    r"refactor|overhaul|system|platform|api|database|infrastructure|pipeline|"
    r"microservice|authentication|authorization|deploy|scale)\b",
    re.IGNORECASE,
)

# Minimum instruction length to consider for meeting flow
_MIN_MEETING_INSTRUCTION_LENGTH = 150

# Max rounds for planning and evaluation meetings
_PLANNING_MEETING_MAX_ROUNDS = 3
_EVALUATION_MEETING_MAX_ROUNDS = 2


class CEOAgent(AgentBase):
    """CEO agent — orchestrates the 5-phase human-like company workflow."""

    async def handle_task(self, message: AgentCommand, session: AsyncSession) -> AgentResponse:
        """Route based on message source: new task, agent response, or plan approval."""
        task_id = str(message.task_id)
        trace_id = str(message.trace_id)

        # Route 1: Agent response (subtask completion aggregation)
        if message.payload.get("_response_aggregation"):
            return await self._handle_agent_response(message, session)

        # Route 2: Plan approval response from user
        if message.payload.get("_plan_approval"):
            return await self._handle_plan_approval_response(message, session)

        # Route 3: Post-execution evaluation result
        if message.payload.get("_evaluation_complete"):
            return await self._handle_evaluation_complete(message, session)

        logger.info(
            "ceo_task_received",
            task_id=task_id,
            trace_id=trace_id,
            instruction=message.instruction[:200],
        )

        # Decide: full 5-phase meeting flow or direct decomposition
        use_meeting = self._should_use_meeting(message)

        if use_meeting:
            return await self._run_meeting_flow(message, session)
        return await self._run_direct_flow(message, session)

    # ─── Meeting flow decision ──────────────────────────────────────────────

    def _should_use_meeting(self, message: AgentCommand) -> bool:
        """Decide if a task warrants the full conference room workflow.

        Uses heuristics:
        - User override via payload flag
        - Instruction length (short = simple)
        - Complexity keyword detection
        - Multi-role involvement hints
        """
        # User override
        if message.payload.get("require_meeting") is True:
            return True
        if message.payload.get("require_meeting") is False:
            return False

        instruction = message.instruction

        # Short instructions are likely simple
        if len(instruction) < _MIN_MEETING_INSTRUCTION_LENGTH:
            return False

        # Check for complexity keywords
        if _COMPLEXITY_KEYWORDS.search(instruction):
            return True

        return False

    # ─── Phase 1-3: Meeting flow (extract → discuss → approve) ────────────

    async def _run_meeting_flow(
        self, message: AgentCommand, session: AsyncSession
    ) -> AgentResponse:
        """Run the full 5-phase meeting workflow for complex tasks.

        Phase 1: Extract requirements via LLM
        Phase 2: Run conference room discussion
        Phase 3: Request user approval (blocks until approved)
        """
        task_id = str(message.task_id)
        trace_id = str(message.trace_id)

        logger.info(
            "ceo_meeting_flow_started",
            task_id=task_id,
            trace_id=trace_id,
        )

        # Phase 1: Extract requirements
        requirements = await self._extract_requirements(message, session)

        # Store requirements in DB
        stmt = select(Task).where(Task.id == task_id)
        result = await session.execute(stmt)
        task_record = result.scalar_one_or_none()
        if task_record:
            task_record.requirements = requirements
            await session.flush()

        # Phase 2: Run planning meeting
        meeting_result = await self._run_planning_meeting(
            message, session, requirements=requirements
        )

        # Phase 3: Request user approval
        plan_summary = await self._synthesize_plan_for_approval(
            message, session,
            requirements=requirements,
            meeting_transcript=meeting_result.get("transcript", ""),
            best_contributions=meeting_result.get("best_contributions", []),
        )

        # Store meeting transcript in DB
        if task_record:
            task_record.meeting_transcript = meeting_result
            task_record.status = TaskStatus.AWAITING_APPROVAL.value
            await session.commit()

        # Create approval record and notify user
        await self._request_plan_approval(
            message, session,
            plan_summary=plan_summary,
            requirements=requirements,
        )

        # Store state for when approval comes back
        await set_working_memory(self.agent_id, task_id, {
            "workflow_phase": "awaiting_approval",
            "original_instruction": message.instruction,
            "requirements": requirements,
            "meeting_result": meeting_result,
            "plan_summary": plan_summary,
            "trace_id": trace_id,
        })

        return AgentResponse(
            task_id=message.task_id,
            trace_id=message.trace_id,
            agent_id=self.agent_id,
            payload={},
            status="success",
            output={
                "action": "decomposed",
                "phase": "awaiting_approval",
                "requirements_count": len(requirements.get("deliverables", [])),
            },
            tokens_used=0,
        )

    async def _extract_requirements(
        self, message: AgentCommand, session: AsyncSession
    ) -> dict[str, Any]:
        """Phase 1: Extract structured requirements from the user's task.

        Uses LLM to analyze the instruction and produce a structured
        requirements list with goals, deliverables, constraints, and
        acceptance criteria.
        """
        task_id = str(message.task_id)

        extract_prompt = (
            "You are the CEO analyzing a task requirement. "
            "Extract and structure what the user needs.\n\n"
            f"Task: {message.instruction}\n\n"
            "Respond ONLY with a JSON object containing:\n"
            '- "summary": one-sentence summary of what the user wants\n'
            '- "goals": list of high-level goals\n'
            '- "deliverables": list of specific deliverables expected\n'
            '- "constraints": list of constraints or limitations mentioned\n'
            '- "acceptance_criteria": list of criteria to judge completion\n'
            '- "suggested_agents": list of agent roles needed '
            '(from: "engineer", "analyst", "writer")\n'
        )

        try:
            result = await self._run_with_retry(extract_prompt, task_id)

            # Record LLM usage
            try:
                usage = result.usage()
                input_tokens = usage.request_tokens or 0
                output_tokens = usage.response_tokens or 0
                model_obj = self.llm_agent.model
                model_name = getattr(model_obj, "model_name", str(model_obj))[:100]
                await record_usage(
                    session=session,
                    task_id=task_id,
                    agent_id=self.agent_id,
                    model_name=model_name,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=calculate_cost(model_name, input_tokens, output_tokens),
                )
            except Exception as exc:
                logger.warning(
                    "ceo_requirements_usage_failed", task_id=task_id, error=str(exc)
                )

            raw = result.output.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                raw = raw.rsplit("```", 1)[0]

            requirements = json.loads(raw)

            logger.info(
                "ceo_requirements_extracted",
                task_id=task_id,
                goals=len(requirements.get("goals", [])),
                deliverables=len(requirements.get("deliverables", [])),
                agents=requirements.get("suggested_agents", []),
            )

            return requirements

        except Exception as exc:
            logger.warning(
                "ceo_requirements_extraction_failed", task_id=task_id, error=str(exc)
            )
            return {
                "summary": message.instruction[:200],
                "goals": [message.instruction],
                "deliverables": ["Complete the requested task"],
                "constraints": [],
                "acceptance_criteria": ["Task completed successfully"],
                "suggested_agents": ["engineer"],
            }

    async def _run_planning_meeting(
        self,
        message: AgentCommand,
        session: AsyncSession,
        *,
        requirements: dict[str, Any],
    ) -> dict[str, Any]:
        """Phase 2: Run a conference room discussion about the requirements.

        Creates a MeetingRoom, invites relevant agents, and runs rounds
        of discussion until convergence or max rounds.

        Returns:
            Dict with transcript, best_contributions, and convergence_report.
        """
        task_id = str(message.task_id)
        trace_id = str(message.trace_id)

        # Determine participants based on suggested agents
        participants = requirements.get("suggested_agents", ["engineer"])
        # Ensure we have at least 2 participants for a meaningful discussion
        if len(participants) < 2:
            if "analyst" not in participants:
                participants.append("analyst")
            elif "engineer" not in participants:
                participants.append("engineer")

        meeting_id = str(uuid4())
        config = MeetingConfig(
            meeting_id=meeting_id,
            parent_task_id=task_id,
            trace_id=trace_id,
            topic=requirements.get("summary", message.instruction[:200]),
            participants=participants,
            max_rounds=_PLANNING_MEETING_MAX_ROUNDS,
            timeout_seconds=180,
        )

        room = await create_meeting(config)

        logger.info(
            "ceo_planning_meeting_created",
            task_id=task_id,
            meeting_id=meeting_id,
            participants=participants,
        )

        # Format requirements for the meeting question
        req_text = json.dumps(requirements, indent=2)
        question = (
            f"We have a new requirement to discuss:\n\n"
            f"{req_text}\n\n"
            f"How should we approach this? Consider:\n"
            f"1. Technical feasibility and approach\n"
            f"2. Potential risks or concerns\n"
            f"3. Estimated effort and dependencies\n"
            f"4. What each of you would need to deliver"
        )

        # Run meeting rounds until convergence
        for round_num in range(_PLANNING_MEETING_MAX_ROUNDS):
            if round_num == 0:
                round_question = question
            else:
                # Follow-up rounds address previous discussion
                report = room.check_convergence()
                if report.recommendation in ("synthesize", "terminate"):
                    break
                round_question = (
                    "Based on the discussion so far, refine your position. "
                    "Address any concerns raised by other agents. "
                    "Are there any gaps or risks we haven't covered?"
                )

            await room.run_meeting_round(
                question=round_question,
                sender_id=self.agent_id,
                wait_seconds=60.0,
                poll_interval=3.0,
            )

        # Get final convergence report
        convergence = room.check_convergence()
        transcript = room.get_transcript()
        best = room.get_best_contributions()

        # Terminate meeting
        conclusion = (
            f"Meeting concluded after {room.current_round} rounds. "
            f"Recommendation: {convergence.recommendation}. "
            f"Reason: {convergence.reason}"
        )
        await room.terminate(conclusion, self.agent_id, reason=convergence.recommendation)
        await close_meeting(meeting_id)

        logger.info(
            "ceo_planning_meeting_concluded",
            task_id=task_id,
            meeting_id=meeting_id,
            rounds=room.current_round,
            recommendation=convergence.recommendation,
        )

        return {
            "meeting_id": meeting_id,
            "transcript": transcript,
            "best_contributions": [
                {"role": m.sender_role, "content": m.content} for m in best
            ],
            "convergence_report": convergence.model_dump(),
            "rounds": room.current_round,
        }

    async def _synthesize_plan_for_approval(
        self,
        message: AgentCommand,
        session: AsyncSession,
        *,
        requirements: dict[str, Any],
        meeting_transcript: str,
        best_contributions: list[dict[str, Any]],
    ) -> str:
        """Synthesize requirements + meeting discussion into a plan for user approval."""
        task_id = str(message.task_id)

        contributions_text = "\n".join(
            f"- [{c['role'].upper()}]: {c['content'][:500]}"
            for c in best_contributions
        )

        synthesis_prompt = (
            "Synthesize the following into a clear execution plan for user approval.\n\n"
            f"Requirements:\n{json.dumps(requirements, indent=2)}\n\n"
            f"Agent discussion highlights:\n{contributions_text}\n\n"
            "Produce a plan with:\n"
            "1. What will be done (specific deliverables)\n"
            "2. How it will be done (approach from the discussion)\n"
            "3. Who will do what (agent assignments)\n"
            "4. Key risks or concerns raised\n\n"
            "Write in plain language for a human reviewer. Be concise."
        )

        try:
            result = await self._run_with_retry(synthesis_prompt, task_id)
            return result.output
        except Exception as exc:
            logger.warning(
                "ceo_plan_synthesis_failed", task_id=task_id, error=str(exc)
            )
            return (
                f"Requirements: {requirements.get('summary', 'N/A')}\n\n"
                f"Deliverables: {requirements.get('deliverables', [])}\n\n"
                f"Agents involved: {requirements.get('suggested_agents', [])}"
            )

    async def _request_plan_approval(
        self,
        message: AgentCommand,
        session: AsyncSession,
        *,
        plan_summary: str,
        requirements: dict[str, Any],
    ) -> None:
        """Phase 3: Create an approval record and notify the user.

        Reuses the existing HumanApproval mechanism with tool_name='plan_approval'.
        """
        task_id = str(message.task_id)

        approval = HumanApproval(
            task_id=task_id,
            agent_id=self.agent_id,
            tool_name="plan_approval",
            action_description=plan_summary[:5000],
            status=ApprovalStatus.PENDING.value,
        )
        session.add(approval)
        await session.flush()

        # Publish to human.input_needed for dashboard notification
        notify_msg = KafkaMessage(
            task_id=message.task_id,
            trace_id=message.trace_id,
            agent_id=self.agent_id,
            payload={
                "reason": "plan_approval",
                "plan_summary": plan_summary[:2000],
                "requirements": requirements,
                "approval_id": str(approval.id),
                "instruction": message.instruction[:500],
            },
        )
        await publish(Topics.HUMAN_INPUT_NEEDED, notify_msg, key=task_id)

        await self._broadcast({
            "event": "plan_approval_needed",
            "agent_id": self.agent_id,
            "task_id": task_id,
            "plan_summary": plan_summary[:500],
        })

        logger.info(
            "ceo_plan_approval_requested",
            task_id=task_id,
            approval_id=str(approval.id),
        )

    async def _handle_plan_approval_response(
        self, message: AgentCommand, session: AsyncSession
    ) -> AgentResponse:
        """Handle user's plan approval or rejection.

        On approval: proceed to Phase 4 (decompose and execute).
        On rejection: re-run Phase 1 with user feedback.
        """
        task_id = str(message.task_id)
        approved = message.payload.get("approved", False)
        feedback = message.payload.get("feedback", "")

        # Load saved workflow state
        state = await get_working_memory(self.agent_id, task_id)
        if not state:
            logger.warning("ceo_plan_approval_no_state", task_id=task_id)
            return AgentResponse(
                task_id=message.task_id,
                trace_id=message.trace_id,
                agent_id=self.agent_id,
                payload={},
                status="failed",
                error="No workflow state found for plan approval",
            )

        if not approved:
            logger.info(
                "ceo_plan_rejected",
                task_id=task_id,
                feedback=feedback[:200],
            )
            # Re-run with feedback incorporated
            revised_instruction = (
                f"{state['original_instruction']}\n\n"
                f"[User feedback on previous plan: {feedback}]"
            )
            revised_message = AgentCommand(
                task_id=message.task_id,
                trace_id=message.trace_id,
                agent_id=message.agent_id,
                payload={"require_meeting": True},
                target_role="ceo",
                instruction=revised_instruction,
            )
            return await self._run_meeting_flow(revised_message, session)

        logger.info("ceo_plan_approved", task_id=task_id)

        # Update task status
        stmt = select(Task).where(Task.id == task_id)
        result = await session.execute(stmt)
        task_record = result.scalar_one_or_none()
        if task_record:
            task_record.status = TaskStatus.RUNNING.value
            await session.flush()

        # Phase 4: Proceed with execution using approved plan
        original_message = AgentCommand(
            task_id=message.task_id,
            trace_id=message.trace_id,
            agent_id=message.agent_id,
            payload={},
            target_role="ceo",
            instruction=state["original_instruction"],
        )

        return await self._run_execution_phase(
            original_message, session,
            requirements=state.get("requirements", {}),
            meeting_result=state.get("meeting_result", {}),
        )

    async def _handle_evaluation_complete(
        self, message: AgentCommand, session: AsyncSession
    ) -> AgentResponse:
        """Handle post-execution evaluation results.

        If evaluation passes, deliver final result.
        If it fails, trigger rework on specific subtasks.
        """
        task_id = str(message.task_id)
        evaluation_passed = message.payload.get("evaluation_passed", True)

        if evaluation_passed:
            logger.info("ceo_evaluation_passed", task_id=task_id)
            # Result already routed to Director → QA via normal flow
            return AgentResponse(
                task_id=message.task_id,
                trace_id=message.trace_id,
                agent_id=self.agent_id,
                payload={},
                status="success",
                output={"action": "decomposed", "phase": "evaluation_passed"},
                tokens_used=0,
            )

        logger.info("ceo_evaluation_failed_rework", task_id=task_id)
        # For now, route to Director anyway — QA will handle rework
        return AgentResponse(
            task_id=message.task_id,
            trace_id=message.trace_id,
            agent_id=self.agent_id,
            payload={},
            status="success",
            output={"action": "decomposed", "phase": "evaluation_rework"},
            tokens_used=0,
        )

    # ─── Phase 4: Execution (direct flow for simple tasks) ──────────────────

    async def _run_direct_flow(
        self, message: AgentCommand, session: AsyncSession
    ) -> AgentResponse:
        """Direct decomposition flow for simple tasks (skips meeting)."""
        task_id = str(message.task_id)
        trace_id = str(message.trace_id)

        # Plan
        plan = await self._create_plan(message, session)

        # Decompose and execute
        return await self._decompose_and_dispatch(message, session, plan=plan)

    async def _run_execution_phase(
        self,
        message: AgentCommand,
        session: AsyncSession,
        *,
        requirements: dict[str, Any],
        meeting_result: dict[str, Any],
    ) -> AgentResponse:
        """Phase 4: Execute the approved plan.

        Uses the meeting discussion to inform the execution plan,
        then decomposes and dispatches as normal.
        """
        task_id = str(message.task_id)

        # Create plan informed by the meeting discussion
        plan = await self._create_plan(message, session)
        # Enrich plan with meeting context
        plan["requirements"] = requirements
        plan["meeting_recommendations"] = meeting_result.get(
            "convergence_report", {}
        ).get("recommendation", "")

        return await self._decompose_and_dispatch(
            message, session, plan=plan, requirements=requirements,
            meeting_result=meeting_result,
        )

    async def _decompose_and_dispatch(
        self,
        message: AgentCommand,
        session: AsyncSession,
        *,
        plan: dict[str, Any],
        requirements: dict[str, Any] | None = None,
        meeting_result: dict[str, Any] | None = None,
    ) -> AgentResponse:
        """Shared decomposition + dispatch logic used by both flows."""
        task_id = str(message.task_id)
        trace_id = str(message.trace_id)

        subtasks = await self._decompose_task(message, session, plan=plan)

        if not subtasks:
            logger.warning(
                "ceo_decomposition_empty",
                task_id=task_id,
                trace_id=trace_id,
                instruction_preview=message.instruction[:200],
                event_tag="decomposition_failure",
            )
            try:
                await write_episode(
                    session=session,
                    agent_id=self.agent_id,
                    task_id=task_id,
                    summary=f"CEO decomposition failed for: {message.instruction[:300]}",
                    full_context={
                        "instruction": message.instruction,
                        "failure_type": "decomposition_empty",
                        "fallback": "engineer",
                    },
                    outcome="failed",
                    tokens_used=0,
                    duration_seconds=0,
                )
            except Exception as mem_exc:
                logger.warning(
                    "ceo_decomposition_failure_write_error",
                    task_id=task_id,
                    error=str(mem_exc),
                )
            subtasks = [{"role": "engineer", "instruction": message.instruction, "depends_on": []}]
        else:
            logger.info(
                "ceo_decomposition_success",
                task_id=task_id,
                trace_id=trace_id,
                subtask_count=len(subtasks),
                event_tag="decomposition_success",
            )

        subtask_ids = await self._create_subtasks(session, message, subtasks)
        await session.commit()

        tracking: dict[str, Any] = {
            "parent_task_id": task_id,
            "original_instruction": message.instruction,
            "plan": plan,
            "requirements": requirements,
            "meeting_result": meeting_result,
            "subtasks": {
                str(sid): {
                    "role": st["role"],
                    "instruction": st["instruction"],
                    "depends_on": [str(subtask_ids[i]) for i in st.get("depends_on", [])],
                    "status": "pending",
                    "output": None,
                }
                for sid, st in zip(subtask_ids, subtasks, strict=False)
            },
            "total": len(subtask_ids),
            "completed": 0,
        }
        await set_working_memory(self.agent_id, task_id, tracking)

        dispatched = 0
        for sid, st in zip(subtask_ids, subtasks, strict=False):
            if not st.get("depends_on"):
                await self._dispatch_subtask(
                    task_id=str(sid),
                    trace_id=trace_id,
                    role=st["role"],
                    instruction=st["instruction"],
                    parent_task_id=task_id,
                )
                tracking["subtasks"][str(sid)]["status"] = "dispatched"
                dispatched += 1

        await set_working_memory(self.agent_id, task_id, tracking)

        logger.info(
            "ceo_task_decomposed",
            task_id=task_id,
            trace_id=trace_id,
            subtask_count=len(subtask_ids),
            dispatched=dispatched,
        )

        return AgentResponse(
            task_id=message.task_id,
            trace_id=message.trace_id,
            agent_id=self.agent_id,
            payload={},
            status="success",
            output={
                "action": "decomposed",
                "subtask_count": len(subtask_ids),
                "subtask_ids": [str(s) for s in subtask_ids],
            },
            tokens_used=0,
        )

    async def _create_plan(
        self, message: AgentCommand, session: AsyncSession
    ) -> dict[str, Any]:
        """Create an execution plan with security and architecture assessment.

        The planning phase happens BEFORE task decomposition. It evaluates:
        - What the task requires and potential approaches
        - Security implications (irreversible actions, external calls, data access)
        - Required tools and their risk levels
        - Dependencies and execution order

        Args:
            message: The incoming task command.
            session: Database session.

        Returns:
            Plan dict with approach, security assessment, and risk level.
        """
        task_id = str(message.task_id)

        plan_prompt = (
            "You are the CEO planning an execution strategy. Analyze this task and create a plan.\n\n"
            f"Task: {message.instruction}\n\n"
            "Respond ONLY with a JSON object containing:\n"
            '- "approach": brief description of how to approach this task\n'
            '- "risk_level": "low" | "medium" | "high"\n'
            '- "security_concerns": list of security concerns (empty if none)\n'
            '- "requires_approval": true if task involves irreversible actions (file writes, emails, external API calls)\n'
            '- "estimated_complexity": "simple" | "moderate" | "complex"\n'
            '- "parallel_possible": true if subtasks can run in parallel\n\n'
            "Risk level guidelines:\n"
            '- "low": read-only operations, research, analysis\n'
            '- "medium": code generation, file creation, content writing\n'
            '- "high": external API calls, email sending, code execution, data modification\n'
        )

        try:
            result = await self._run_with_retry(plan_prompt, task_id)

            # Record planning LLM usage
            try:
                usage = result.usage()
                input_tokens = usage.request_tokens or 0
                output_tokens = usage.response_tokens or 0
                model_obj = self.llm_agent.model
                model_name = getattr(model_obj, "model_name", str(model_obj))[:100]
                await record_usage(
                    session=session,
                    task_id=task_id,
                    agent_id=self.agent_id,
                    model_name=model_name,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=calculate_cost(model_name, input_tokens, output_tokens),
                )
            except Exception as exc:
                logger.warning("ceo_plan_usage_tracking_failed", task_id=task_id, error=str(exc))

            raw = result.output.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                raw = raw.rsplit("```", 1)[0]

            plan = json.loads(raw)

            logger.info(
                "ceo_plan_created",
                task_id=task_id,
                risk_level=plan.get("risk_level", "unknown"),
                requires_approval=plan.get("requires_approval", False),
                complexity=plan.get("estimated_complexity", "unknown"),
                security_concerns=len(plan.get("security_concerns", [])),
            )

            return plan

        except Exception as exc:
            logger.warning("ceo_planning_failed", task_id=task_id, error=str(exc))
            # Fallback: assume moderate risk
            return {
                "approach": "Direct execution — planning phase failed",
                "risk_level": "medium",
                "security_concerns": [],
                "requires_approval": False,
                "estimated_complexity": "moderate",
                "parallel_possible": False,
            }

    async def _decompose_task(
        self, message: AgentCommand, session: AsyncSession,
        *, plan: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Use LLM to analyze the task and produce a decomposition plan."""
        task_id = str(message.task_id)

        plan_context = ""
        if plan:
            plan_context = (
                f"\n\nExecution plan:\n"
                f"- Approach: {plan.get('approach', 'N/A')}\n"
                f"- Risk level: {plan.get('risk_level', 'medium')}\n"
                f"- Complexity: {plan.get('estimated_complexity', 'moderate')}\n"
                f"- Security concerns: {plan.get('security_concerns', [])}\n"
                f"- Parallel execution possible: {plan.get('parallel_possible', False)}\n"
                f"\nUse this plan to guide your decomposition. "
                f"If risk is 'high', ensure irreversible actions are explicit.\n"
            )

        decompose_prompt = (
            f"Decompose the following task into subtasks.\n\n"
            f"Task: {message.instruction}\n"
            f"{plan_context}\n"
            f"Available specialist agents:\n"
            f"- engineer: code, debugging, technical tasks\n"
            f"- analyst: research, data analysis, reports\n"
            f"- writer: content, emails, documentation\n\n"
            f"Respond ONLY with a JSON array of subtasks. Each subtask must have:\n"
            f'- "role": one of "engineer", "analyst", "writer"\n'
            f'- "instruction": clear, specific instructions\n'
            f'- "depends_on": array of subtask indices (0-based) this depends on\n\n'
            f"For simple single-agent tasks, return a single-item array.\n"
            'Example: [{"role": "analyst", "instruction": "Research...", "depends_on": []}]'
        )

        try:
            result = await self._run_with_retry(decompose_prompt, task_id)

            # Record LLM usage
            try:
                usage = result.usage()
                input_tokens = usage.request_tokens or 0
                output_tokens = usage.response_tokens or 0
                model_obj = self.llm_agent.model
                model_name = getattr(model_obj, "model_name", str(model_obj))[:100]
                await record_usage(
                    session=session,
                    task_id=task_id,
                    agent_id=self.agent_id,
                    model_name=model_name,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=calculate_cost(model_name, input_tokens, output_tokens),
                )
            except Exception as exc:
                logger.warning("ceo_usage_tracking_failed", task_id=task_id, error=str(exc))

            # Parse JSON from LLM response
            raw = result.output.strip()
            # Handle markdown code blocks
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                raw = raw.rsplit("```", 1)[0]

            subtasks = json.loads(raw)

            # Validate structure
            if not isinstance(subtasks, list) or not subtasks:
                logger.warning("ceo_invalid_decomposition", task_id=task_id, raw=raw[:200])
                return []

            validated: list[dict[str, Any]] = []
            for st in subtasks:
                role = st.get("role", "engineer")
                if role not in _DELEGATABLE_ROLES:
                    role = "engineer"
                validated.append(
                    {
                        "role": role,
                        "instruction": st.get("instruction", message.instruction),
                        "depends_on": st.get("depends_on", []),
                    }
                )
            return validated

        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("ceo_decomposition_parse_error", task_id=task_id, error=str(exc))
            return []
        except Exception as exc:
            logger.error("ceo_decomposition_failed", task_id=task_id, error=str(exc))
            return []

    async def _create_subtasks(
        self,
        session: AsyncSession,
        parent_message: AgentCommand,
        subtasks: list[dict[str, Any]],
    ) -> list[UUID]:
        """Create subtask records in the tasks table with parent_task_id linkage."""
        subtask_ids: list[UUID] = []
        parent_task_id = str(parent_message.task_id)

        for st in subtasks:
            subtask = Task(
                trace_id=str(parent_message.trace_id),
                parent_task_id=parent_task_id,
                instruction=st["instruction"],
                status=TaskStatus.QUEUED.value,
                source="internal",
            )
            session.add(subtask)
            await session.flush()
            subtask_ids.append(subtask.id)

            logger.info(
                "subtask_created",
                subtask_id=str(subtask.id),
                parent_task_id=parent_task_id,
                role=st["role"],
            )

        return subtask_ids

    async def _dispatch_subtask(
        self,
        *,
        task_id: str,
        trace_id: str,
        role: str,
        instruction: str,
        parent_task_id: str,
    ) -> None:
        """Publish a subtask command to agent.commands."""
        command = AgentCommand(
            task_id=UUID(task_id),
            trace_id=UUID(trace_id),
            agent_id=self.agent_id,
            payload={
                "parent_task_id": parent_task_id,
                "original_role": role,
            },
            target_role=role,
            instruction=instruction,
        )
        await publish(Topics.AGENT_COMMANDS, command, key=task_id)

        logger.info(
            "subtask_dispatched",
            task_id=task_id,
            target_role=role,
            parent_task_id=parent_task_id,
        )

    async def _handle_agent_response(
        self, message: AgentCommand, session: AsyncSession
    ) -> AgentResponse:
        """Handle an agent response — update tracking and aggregate if all done.

        This is called when the result consumer forwards responses for subtasks
        that belong to a multi-agent workflow.
        """
        subtask_id = str(message.payload.get("subtask_id", ""))
        parent_task_id = str(message.payload.get("parent_task_id", ""))
        subtask_output = message.payload.get("subtask_output", "")
        subtask_status = message.payload.get("subtask_status", "success")

        if not parent_task_id:
            logger.warning("ceo_response_missing_parent", subtask_id=subtask_id)
            return AgentResponse(
                task_id=message.task_id,
                trace_id=message.trace_id,
                agent_id=self.agent_id,
                payload={},
                status="failed",
                error="Missing parent_task_id in response",
            )

        # Load tracking state from working memory
        tracking = await get_working_memory(self.agent_id, parent_task_id)
        if not tracking:
            logger.warning("ceo_tracking_not_found", parent_task_id=parent_task_id)
            # Use orchestration action to prevent infinite forwarding loop:
            # without this, the "failed" response goes to agent.responses →
            # result consumer sees it's a subtask → forwards back → repeat.
            return AgentResponse(
                task_id=message.task_id,
                trace_id=message.trace_id,
                agent_id=self.agent_id,
                payload={},
                status="failed",
                output={"action": "subtask_tracked"},
                error="No tracking state found",
            )

        # Update subtask status — count any terminal status (including failed)
        # so the workflow doesn't get stuck when a subtask fails
        if subtask_id in tracking["subtasks"]:
            tracking["subtasks"][subtask_id]["status"] = subtask_status
            tracking["subtasks"][subtask_id]["output"] = subtask_output
            if subtask_status in ("success", "completed", "failed", "partial", "escalated"):
                tracking["completed"] = tracking.get("completed", 0) + 1

        await set_working_memory(self.agent_id, parent_task_id, tracking)

        # Check for newly unblocked subtasks (dependencies resolved)
        await self._dispatch_unblocked(parent_task_id, tracking, str(message.trace_id))

        # Check if all subtasks are complete
        if tracking["completed"] >= tracking["total"]:
            return await self._aggregate_and_route_to_director(parent_task_id, tracking, message, session)

        logger.info(
            "ceo_subtask_completed",
            subtask_id=subtask_id,
            parent_task_id=parent_task_id,
            completed=tracking["completed"],
            total=tracking["total"],
        )

        return AgentResponse(
            task_id=message.task_id,
            trace_id=message.trace_id,
            agent_id=self.agent_id,
            payload={},
            status="success",
            output={
                "action": "subtask_tracked",
                "completed": tracking["completed"],
                "total": tracking["total"],
            },
            tokens_used=0,
        )

    async def _dispatch_unblocked(
        self, parent_task_id: str, tracking: dict[str, Any], trace_id: str
    ) -> None:
        """Dispatch subtasks whose dependencies are now all resolved (done or failed)."""
        completed_ids = {
            sid
            for sid, st in tracking["subtasks"].items()
            if st["status"] in ("success", "completed", "failed", "partial", "escalated")
        }

        for sid, st in tracking["subtasks"].items():
            if st["status"] not in ("pending",):
                continue
            deps = st.get("depends_on", [])
            if all(d in completed_ids for d in deps):
                # Include outputs from dependencies in the instruction
                dep_context = ""
                for dep_id in deps:
                    dep_output = tracking["subtasks"].get(dep_id, {}).get("output", "")
                    if dep_output:
                        dep_context += f"\n\nContext from previous step:\n{dep_output}"

                instruction = st["instruction"]
                if dep_context:
                    instruction += dep_context

                await self._dispatch_subtask(
                    task_id=sid,
                    trace_id=trace_id,
                    role=st["role"],
                    instruction=instruction,
                    parent_task_id=parent_task_id,
                )
                st["status"] = "dispatched"

        await set_working_memory(self.agent_id, parent_task_id, tracking)

    async def _aggregate_and_route_to_director(
        self,
        parent_task_id: str,
        tracking: dict[str, Any],
        message: AgentCommand,
        session: AsyncSession,
    ) -> AgentResponse:
        """Aggregate all subtask outputs and send to Director for synthesis.

        Includes convergence data from the planning meeting if available,
        so the Director can factor meeting dynamics into synthesis.
        """
        # Collect all outputs
        outputs: list[str] = []
        for _sid, st in tracking["subtasks"].items():
            output = st.get("output", "(no output)")
            outputs.append(f"[{st['role'].upper()}] {output}")

        aggregated = "\n\n---\n\n".join(outputs)

        logger.info(
            "ceo_aggregating_results",
            parent_task_id=parent_task_id,
            subtask_count=tracking["total"],
        )

        # Include convergence report from planning meeting if available
        meeting_result = tracking.get("meeting_result")
        convergence_report = None
        if meeting_result:
            convergence_report = meeting_result.get("convergence_report")

        # Route to Director for synthesis (Director then forwards to QA)
        director_payload: dict[str, Any] = {
            "aggregated_output": aggregated,
            "original_instruction": tracking.get("original_instruction", ""),
            "subtask_count": tracking["total"],
            "original_role": "ceo",
            "execution_plan": tracking.get("plan", {}),
        }
        if convergence_report:
            director_payload["convergence_report"] = convergence_report

        requirements = tracking.get("requirements")
        if requirements:
            director_payload["requirements"] = requirements

        director_command = AgentCommand(
            task_id=UUID(parent_task_id),
            trace_id=message.trace_id,
            agent_id=self.agent_id,
            payload=director_payload,
            target_role=AgentRole.DIRECTOR.value,
            instruction=(
                f"Synthesize the best result from agent contributions:\n\n"
                f"Original request: {tracking.get('original_instruction', '')}\n\n"
                f"Agent contributions:\n{aggregated}"
            ),
        )
        await publish(Topics.DIRECTOR_REVIEW, director_command, key=parent_task_id)

        # Phase 5: Run post-execution evaluation if this was a meeting workflow
        if meeting_result and requirements:
            await self._run_evaluation_meeting(
                message, session,
                parent_task_id=parent_task_id,
                tracking=tracking,
                aggregated_output=aggregated,
            )

        logger.info(
            "ceo_routed_to_director",
            parent_task_id=parent_task_id,
            has_convergence=convergence_report is not None,
        )

        return AgentResponse(
            task_id=message.task_id,
            trace_id=message.trace_id,
            agent_id=self.agent_id,
            payload={},
            status="success",
            output={
                "action": "aggregated_and_sent_to_director",
                "parent_task_id": parent_task_id,
                "subtask_count": tracking["total"],
            },
            tokens_used=0,
        )

    # ─── Phase 5: Post-execution evaluation ──────────────────────────────────

    async def _run_evaluation_meeting(
        self,
        message: AgentCommand,
        session: AsyncSession,
        *,
        parent_task_id: str,
        tracking: dict[str, Any],
        aggregated_output: str,
    ) -> None:
        """Phase 5: Reconvene agents to evaluate if the output meets requirements.

        QA leads the evaluation, and the original agents review their work
        against the requirements.
        """
        requirements = tracking.get("requirements", {})
        if not requirements:
            return

        trace_id = str(message.trace_id)

        # Get unique roles that participated in execution
        agent_roles = list({st["role"] for st in tracking["subtasks"].values()})
        # Add QA as lead evaluator
        participants = list(set(agent_roles + ["qa"]))

        meeting_id = str(uuid4())
        config = MeetingConfig(
            meeting_id=meeting_id,
            parent_task_id=parent_task_id,
            trace_id=trace_id,
            topic="Post-execution evaluation: Does the output meet requirements?",
            participants=participants,
            max_rounds=_EVALUATION_MEETING_MAX_ROUNDS,
            timeout_seconds=120,
        )

        room = await create_meeting(config)

        question = (
            f"Evaluate whether this output meets the original requirements.\n\n"
            f"Requirements:\n{json.dumps(requirements, indent=2)}\n\n"
            f"Output produced:\n{aggregated_output[:3000]}\n\n"
            f"For each requirement, state if it is:\n"
            f"- MET: requirement is satisfied\n"
            f"- PARTIAL: partially addressed, needs work\n"
            f"- NOT MET: not addressed at all\n\n"
            f"Overall verdict: PASS or FAIL"
        )

        await room.run_meeting_round(
            question=question,
            sender_id=self.agent_id,
            wait_seconds=45.0,
            poll_interval=3.0,
        )

        # Check evaluation consensus
        convergence = room.check_convergence()
        transcript = room.get_transcript()

        await room.terminate(
            f"Evaluation complete. {convergence.recommendation}",
            self.agent_id,
            reason="evaluation",
        )
        await close_meeting(meeting_id)

        logger.info(
            "ceo_evaluation_meeting_concluded",
            parent_task_id=parent_task_id,
            meeting_id=meeting_id,
            rounds=room.current_round,
        )

    async def _run_with_retry(self, user_message: str, task_id: str) -> Any:
        """Run LLM agent with retry logic for transient errors."""
        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                return await self.llm_agent.run(user_message)
            except Exception as exc:
                last_error = exc
                error_str = str(exc)

                if "429" in error_str or "rate_limit" in error_str.lower():
                    backoff = _RETRY_BACKOFF_SECONDS[min(attempt, len(_RETRY_BACKOFF_SECONDS) - 1)]
                    logger.warning(
                        "rate_limit_retry",
                        task_id=task_id,
                        attempt=attempt + 1,
                        backoff_seconds=backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue

                if "tool_use_failed" in error_str or "tool call validation" in error_str:
                    logger.warning(
                        "tool_call_failed_retry_without_tools",
                        task_id=task_id,
                        attempt=attempt + 1,
                    )
                    no_tools_agent = PydanticAgent(
                        model=self.llm_agent.model,
                        system_prompt=(
                            "You are a CEO who decomposes tasks. "
                            "Respond with a JSON array of subtasks."
                        ),
                    )
                    return await no_tools_agent.run(user_message)

                raise

        raise last_error  # type: ignore[misc]
