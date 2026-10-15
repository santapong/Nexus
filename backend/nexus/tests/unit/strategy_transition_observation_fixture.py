"""Typed supplied-data transition fixture. No actual native proof/admission or reader stub."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID

from nexus.company.management.plan_catalog import PlanAdmissionCatalog
from nexus.company.management.plans import PlanPayload
from nexus.company.management.strategy_transition_observation import StrategyTransitionObservation
from nexus.company.strategy.current_proof_contracts import StrategyCurrentProof
from nexus.company.strategy.owner_selection import describe_strategy_selection
from nexus.tests.unit.strategy_transition_observation_data import transition_data


@dataclass
class TransitionCase:
    payload: PlanPayload
    catalog: PlanAdmissionCatalog
    proof: StrategyCurrentProof
    observation: StrategyTransitionObservation
    now: datetime

    def at_head_two(self) -> StrategyTransitionObservation:
        initial = replace(
            self.proof.initial, pair=replace(self.proof.initial.pair, plan=self.payload)
        )
        current = replace(
            self.proof.current, pair=replace(self.proof.current.pair, plan=self.payload)
        )
        proof = replace(
            self.proof,
            initial=initial,
            current=current,
            observed_at=self.now + timedelta(seconds=1),
        )
        return replace(self.observation, proof=proof)

    def changed_fingerprint(self, field: str) -> StrategyTransitionObservation:
        result = self.at_head_two()
        value = getattr(result.proof, field)
        if field.endswith("fence"):
            changed = value + 1
        elif field == "selection":
            changed = value.model_copy(update={"candidate_scope_sha256": "e" * 64})
        elif field == "original":
            changed = value.model_copy(update={"original_intent_fence": 2})
        elif field == "acceptance":
            changed = value.model_copy(
                update={"recorded_at": value.recorded_at + timedelta(seconds=1)}
            )
        elif field == "brief":
            changed = value.model_copy(update={"deployed_state": "changed"})
        elif field == "verifier":
            changed = replace(
                value, parameters=value.parameters.model_copy(update={"output_sha256": "e" * 64})
            )
        else:
            changed = value.model_copy(update={"result_sha256": "e" * 64})
        return replace(result, proof=replace(result.proof, **{field: changed}))

    def expiring(self, which: str) -> StrategyTransitionObservation:
        if which == "plan":
            grant = self.observation.admission.window.grants[0]
            window = replace(
                self.observation.admission.window,
                grants=(replace(grant, expires_at=self.now + timedelta(seconds=10)),),
            )
            return replace(
                self.observation, admission=replace(self.observation.admission, window=window)
            )
        resource_grant = self.proof.initial.grants[0].model_copy(
            update={"expires_at": self.now + timedelta(seconds=10)}
        )
        read = replace(self.proof.initial, grants=(resource_grant,))
        return replace(self.observation, proof=replace(self.proof, initial=read))

    def splice(self, field: str) -> None:
        if field == "selection":
            self.payload = self.payload.model_copy(update={"strategy_selection": None})
        elif field in {"goal", "root", "plan"}:
            if field == "goal":
                self.payload = self.payload.model_copy(
                    update={"goal": self.payload.goal.model_copy(update={"goal_id": UUID(int=999)})}
                )
            elif field == "root":
                self.payload = self.payload.model_copy(
                    update={
                        "procedure": self.payload.procedure.model_copy(
                            update={"procedure_id": UUID(int=999)}
                        )
                    }
                )
            else:
                self.payload = self.payload.model_copy(
                    update={"plan": self.payload.plan.model_copy(update={"plan_id": UUID(int=999)})}
                )
        elif field == "sv":
            self.proof.current.pair.verifier.actor_id = UUID(int=999)
        elif field == "registration":
            self.proof.current.pair.author.registration_hash = "e" * 64
        elif field == "policy":
            original = self.proof.original.prepared.original
            prepared = self.proof.original.prepared.model_copy(
                update={
                    "original": original.model_copy(
                        update={
                            "policy": original.policy.model_copy(update={"scope_sha256": "e" * 64})
                        }
                    )
                }
            )
            self.proof = replace(
                self.proof, original=self.proof.original.model_copy(update={"prepared": prepared})
            )
        elif field == "brief":
            self.proof = replace(
                self.proof,
                brief=self.proof.brief.model_copy(update={"source_manifest_sha256": "e" * 64}),
            )
        elif field == "acceptance":
            self.proof = replace(
                self.proof,
                acceptance=self.proof.acceptance.model_copy(
                    update={"acceptance_id": UUID(int=999)}
                ),
            )
        else:
            selected = describe_strategy_selection(
                self.proof.brief,
                self.proof.acceptance,
                self.proof.brief.candidates[1].scope.candidate_id,
            )
            self.payload = self.payload.model_copy(update={"strategy_selection": selected})
            self.proof = replace(self.proof, selection=selected)


def transition_case(head: int = 1) -> TransitionCase:
    """Synchronous typed context; genuine synthetic witness, descriptive model/proof data only."""
    data = transition_data(head)
    proof = data.observation.proof
    return TransitionCase(data.payload, proof.current.catalog, proof, data.observation, data.now)
