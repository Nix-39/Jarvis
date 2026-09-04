import time
import uuid
import threading
import concurrent.futures
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable
from dataclasses import dataclass, field

from core.logger import get_logger

logger = get_logger(__name__)

# --- System Limits ---
_MAX_MESSAGE_LENGTH: int = 10_000


# ------------------------------------------------------------------ #
#  Agent Contract                                                    #
# ------------------------------------------------------------------ #

@runtime_checkable
class Agent(Protocol):
    """
    The contract that ALL agents must implement.
    The Planner only calls handle() – nothing else.
    """
    def handle(self, action: str, payload: Dict[str, Any]) -> str:
        """Executes a specific action with the given payload and returns a string response."""
        ...


# ------------------------------------------------------------------ #
#  Data Models                                                       #
# ------------------------------------------------------------------ #

@dataclass(frozen=True)
class ExecutionStep:
    """An atomic task within the plan. Immutable for thread safety."""
    step_id: int
    agent_id: str                # Matches the key in agent_registry
    action: str                  # What the agent should do (e.g. "execute", "summarize")
    payload: Dict[str, Any]
    depends_on: List[int] = field(default_factory=list)  # Steps that must complete first
    max_retries: int = 2         # Standardized to 2 for operational reliability
    timeout_seconds: int = 30    # Prevents hangs in local systems


@dataclass(frozen=True)
class ExecutionPlan:
    """
    The structured contract created by the Planner. Immutable.
    """
    plan_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    target_agent: str = "unknown"
    steps: List[ExecutionStep] = field(default_factory=list)
    verification_rules: Optional[Dict[str, Any]] = None
    requires_human_approval: bool = False


@dataclass(frozen=True)
class StepResult:
    """The result of a single execution step. Immutable history."""
    step_id: int
    success: bool
    response: Optional[str]
    attempts: int
    error: Optional[str] = None
    duration_seconds: float = 0.0


@dataclass(frozen=True)
class PlannerResult:
    """
    What the Planner returns to the Router/Orchestrator.
    Separates metadata/telemetry from the final answer.
    """
    plan_id: str
    final_response: str
    success: bool
    steps_completed: int
    steps_failed: int
    step_results: List[StepResult]
    agent_used: str
    execution_time_seconds: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    error: Optional[str] = None


# ------------------------------------------------------------------ #
#  Planner                                                           #
# ------------------------------------------------------------------ #

class Planner:
    """
    Coordinates work between the Router and the Agents.
    Thread-safe, platform-independent, and optimized for local hardware.
    """

    def __init__(self, agent_registry: Dict[str, Agent]):
        """
        Raises:
            ValueError: If the registry is empty or if agents fail the protocol validation.
        """
        if not agent_registry:
            raise ValueError("[Planner] agent_registry cannot be empty.")

        # Strict validation of configuration at startup (Fail-Fast)
        for agent_id, agent in agent_registry.items():
            if not isinstance(agent_id, str) or not agent_id.strip():
                raise ValueError(f"[Planner] Invalid agent key: '{agent_id}'. Must be a non-empty string.")
            if not isinstance(agent, Agent):
                raise ValueError(
                    f"[Planner] Agent '{agent_id}' does not implement the Agent protocol (missing handle method)."
                )

        self._agents: Dict[str, Agent] = agent_registry
        self._pipeline_lock: threading.Lock = threading.Lock()

        logger.info(
            "Planner initialized | available_agents=%s",
            list(self._agents.keys())
        )

    # ------------------------------------------------------------------ #
    #  Public Contract                                                   #
    # ------------------------------------------------------------------ #

    def run(self, target_agent: str, user_message: str) -> PlannerResult:
        """
        Main entry point for orchestration. Receives target agent and message.
        """
        # Generate a unique plan ID immediately for early traceability
        plan_id = str(uuid.uuid4())

        # --- Defensive Input Validation ---
        if not isinstance(target_agent, str) or not target_agent.strip():
            return self._error_result(plan_id, "Invalid or empty target_agent received.", "UNKNOWN")

        if not user_message or not user_message.strip():
            return self._error_result(plan_id, "Empty user message received.", target_agent)

        if len(user_message) > _MAX_MESSAGE_LENGTH:
            return self._error_result(
                plan_id,
                f"Message too long ({len(user_message)} chars). Max limit is {_MAX_MESSAGE_LENGTH}.",
                target_agent
            )

        normalized_target = target_agent.strip()

        # Fail-fast if the requested agent does not exist in our registry
        if normalized_target not in self._agents:
            error_msg = f"Requested agent '{normalized_target}' is not registered in the system."
            logger.error("[Planner][%s] Fail-Fast triggered: %s", plan_id, error_msg)
            return self._error_result(plan_id, error_msg, normalized_target)

        logger.info("[%s] Starting execution plan for target agent: %s", plan_id, normalized_target)

        plan = self._create_plan(plan_id, normalized_target, user_message)
        result = self._execute_plan(plan)
        return result

    # ------------------------------------------------------------------ #
    #  Private Logic                                                     #
    # ------------------------------------------------------------------ #

    def _create_plan(self, plan_id: str, target_agent: str, user_message: str) -> ExecutionPlan:
        """
        Builds the execution plan. Fast, local, and deterministic.
        """
        step = ExecutionStep(
            step_id=1,
            agent_id=target_agent,
            action="execute",
            payload={"message": user_message},
        )

        logger.debug("[%s] Plan created | Target Agent=%s | Steps=1", plan_id, target_agent)

        return ExecutionPlan(
            plan_id=plan_id,
            target_agent=target_agent,
            steps=[step],
        )

    def _execute_plan(self, plan: ExecutionPlan) -> PlannerResult:
        """
        Executes the steps in the plan sequentially with thread-safe context sharing.
        """
        start_plan_time = time.monotonic()
        step_results: List[StepResult] = []
        failed_step_ids: set = set()
        pipeline_context: Dict[str, Any] = {}

        for step in plan.steps:
            # --- Dependency Check ---
            blocking = [dep for dep in step.depends_on if dep in failed_step_ids]
            if blocking:
                logger.warning(
                    "[%s] Step %s skipped - dependent steps %s failed.",
                    plan.plan_id,
                    step.step_id,
                    blocking
                )
                step_results.append(StepResult(
                    step_id=step.step_id,
                    success=False,
                    response=None,
                    attempts=0,
                    error=f"Blocked by failed steps: {blocking}",
                ))
                failed_step_ids.add(step.step_id)
                continue

            # --- Agent Lookup (Double-check security) ---
            agent = self._agents.get(step.agent_id)
            if not agent:
                logger.error("[%s] Step %s: Agent missing for '%s'", plan.plan_id, step.step_id, step.agent_id)
                step_results.append(StepResult(
                    step_id=step.step_id,
                    success=False,
                    response=None,
                    attempts=0,
                    error=f"Agent missing in registry: '{step.agent_id}'",
                ))
                failed_step_ids.add(step.step_id)
                continue

            # --- Thread-safe Deep Copy of Pipeline Context ---
            with self._pipeline_lock:
                enriched_payload = {
                    **step.payload,
                    "pipeline_context": dict(pipeline_context)  # Sends a copy, not a reference
                }

            # --- Execution with Retry ---
            step_result = self._run_step_with_retry(plan.plan_id, agent, step, enriched_payload)
            step_results.append(step_result)

            if step_result.success and step_result.response:
                with self._pipeline_lock:
                    pipeline_context[f"step_{step.step_id}_output"] = step_result.response
            else:
                failed_step_ids.add(step.step_id)
                logger.error("[%s] Step %s failed permanently. Aborting execution plan.", plan.plan_id, step.step_id)
                break

        # --- Aggregate Final Results ---
        execution_time = time.monotonic() - start_plan_time
        steps_completed = sum(1 for r in step_results if r.success)
        steps_failed = sum(1 for r in step_results if not r.success)
        success = steps_failed == 0 and steps_completed > 0

        responses = [r.response for r in step_results if r.success and r.response]
        final_response = "\n".join(responses) if responses else "Could not generate a response."

        logger.info(
            "[%s] Plan execution finished | success=%s | completed=%s | failed=%s | duration=%ss",
            plan.plan_id,
            success,
            steps_completed,
            steps_failed,
            round(execution_time, 2)
        )

        return PlannerResult(
            plan_id=plan.plan_id,
            final_response=final_response,
            success=success,
            steps_completed=steps_completed,
            steps_failed=steps_failed,
            step_results=step_results,
            agent_used=plan.target_agent,
            execution_time_seconds=round(execution_time, 2)
        )

    def _run_step_with_retry(self, plan_id: str, agent: Agent, step: ExecutionStep, payload: Dict[str, Any]) -> StepResult:
        """
        Runs a step with thread-safe timeout and retry logic.
        Works identically on Windows, macOS, and Linux.
        """
        last_error: Optional[str] = None
        start_time = time.monotonic()

        for attempt in range(1, step.max_retries + 1):
            try:
                logger.debug(
                    "[%s] Executing step %s | Attempt %s/%s | action=%s | timeout=%ss",
                    plan_id,
                    step.step_id,
                    attempt,
                    step.max_retries,
                    step.action,
                    step.timeout_seconds
                )

                # Platform-independent timeout via ThreadPoolExecutor
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(agent.handle, step.action, payload)
                    response = future.result(timeout=step.timeout_seconds)

                duration = time.monotonic() - start_time
                logger.info(
                    "[%s] Step %s completed | attempt=%s | duration=%s seconds",
                    plan_id,
                    step.step_id,
                    attempt,
                    round(duration, 2)
                )

                return StepResult(
                    step_id=step.step_id,
                    success=True,
                    response=response,
                    attempts=attempt,
                    duration_seconds=round(duration, 2),
                )

            except concurrent.futures.TimeoutError:
                last_error = f"Timeout after {step.timeout_seconds}s"
                logger.warning("[%s] Step %s timed out (Attempt %s)", plan_id, step.step_id, attempt)
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "[%s] Step %s failed (Attempt %s/%s): %s",
                    plan_id,
                    step.step_id,
                    attempt,
                    step.max_retries,
                    e
                )

        duration = time.monotonic() - start_time
        logger.error(
            "[%s] Step %s failed permanently after %s attempts. Last error: %s",
            plan_id,
            step.step_id,
            step.max_retries,
            last_error
        )

        return StepResult(
            step_id=step.step_id,
            success=False,
            response=None,
            attempts=step.max_retries,
            error=last_error,
            duration_seconds=round(duration, 2),
        )

    @staticmethod
    def _error_result(plan_id: str, reason: str, agent_id: str = "unknown") -> PlannerResult:
        """Safe fallback for malformed requests or early aborts."""
        logger.warning("[%s] Early abort: %s", plan_id, reason)
        return PlannerResult(
            plan_id=plan_id,
            final_response=reason,
            success=False,
            steps_completed=0,
            steps_failed=0,
            step_results=[],
            agent_used=agent_id,
            error=reason,
            execution_time_seconds=0.0
        )


if __name__ == "__main__":
    # --------------------------------------------------------------
    # Simple Local Integration Test
    # --------------------------------------------------------------
    print("=== TESTING PLANNER CONTRACT ===")
    
    class DummyAgent:
        def handle(self, action: str, payload: Dict[str, Any]) -> str:
            msg = payload.get("message", "")
            return f"[DummyAgent Echo] Processed action '{action}' with input: '{msg}'"

    registry = {
        "general_agent": DummyAgent(),
        "business_agent": DummyAgent()
    }

    planner = Planner(agent_registry=registry)
    
    # Test normal execution
    test_result = planner.run("business_agent", "Hello Jarvis!")
    print(f"Success: {test_result.success}")
    print(f"Response: {test_result.final_response}")
    print(f"Total Execution Time: {test_result.execution_time_seconds}s")
    print(f"Plan ID: {test_result.plan_id}")
    
    # Test Fail-Fast (Unknown Agent)
    fail_result = planner.run("career_agent", "Hello!")
    print(f"Fail-Fast test success (Should be False): {fail_result.success}")
    print(f"Error Message: {fail_result.error}")