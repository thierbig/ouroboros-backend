"""Ouroboros agent loop -- ReAct pattern with streaming events."""

import json
from datetime import datetime, timezone
from typing import AsyncIterator
from core.adapters.base import LLMAdapter, AgentResponse, TokenUsage
from core.registry import ToolRegistry
from core.prompt import build_system_prompt


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

MAX_TOOL_RESULT_CHARS = 100_000


class Agent:
    def __init__(
        self,
        adapter: LLMAdapter,
        registry: ToolRegistry,
        max_iterations: int = 100,
        working_dir: str | None = None,
    ):
        self.adapter = adapter
        self.registry = registry
        self.max_iterations = max_iterations
        self.working_dir = working_dir
        self._interrupt_requested = False
        self._total_tokens = 0

    def interrupt(self):
        self._interrupt_requested = True

    async def run(
        self,
        user_message: str,
        history: list[dict],
    ) -> AsyncIterator[dict]:
        """Run the agent loop. Yields events as they happen.

        Updates history in-place so the caller retains conversation context.
        """
        self._interrupt_requested = False
        self._total_tokens = 0

        system_prompt = build_system_prompt(self.working_dir)

        # Add user message to history (caller's list, persists across turns)
        history.append({"role": "user", "content": user_message, "timestamp": _now()})

        messages = [
            {"role": "system", "content": system_prompt},
            *history,
        ]

        tools = self.registry.get_definitions()
        iteration = 0

        while iteration < self.max_iterations:
            if self._interrupt_requested:
                yield {"type": "response", "content": "Agent interrupted by user."}
                break

            # Budget warning injection (as separate message, not mutating tool results)
            budget_warning = self._get_budget_warning(iteration)
            if budget_warning:
                messages.append({"role": "user", "content": budget_warning})

            # Emit status so frontend knows what's happening
            if iteration == 0:
                yield {"type": "status", "message": "Thinking..."}
            else:
                yield {"type": "status", "message": f"Thinking... (turn {iteration + 1})"}

            # Call LLM (with retry on timeout)
            try:
                response = await self.adapter.chat(messages, tools)
            except Exception as e:
                err_name = type(e).__name__
                # Inject error as a system hint so the agent can learn and adapt
                messages.append({
                    "role": "user",
                    "content": f"[SYSTEM] LLM call failed: {err_name}: {e}. "
                    "Try to continue your task. If you were in the middle of something, "
                    "pick up where you left off. Save a lesson about this error.",
                    "timestamp": _now(),
                })
                history.append(messages[-1])
                yield {"type": "self_correcting", "error": f"LLM error: {err_name}"}
                iteration += 1
                continue
            self._total_tokens += response.usage.total_tokens

            # No tool calls -- final response
            if not response.has_tool_calls:
                yield {"type": "response", "content": response.content or ""}
                final_msg = {"role": "assistant", "content": response.content or "", "timestamp": _now()}
                messages.append(final_msg)
                history.append(final_msg)
                break

            # Build assistant message with tool calls
            assistant_msg = {
                "role": "assistant",
                "content": response.content or "",
                "timestamp": _now(),
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.args),
                        },
                    }
                    for tc in response.tool_calls
                ],
            }
            messages.append(assistant_msg)
            history.append(assistant_msg)

            # Execute each tool call
            for tc in response.tool_calls:
                yield {"type": "tool_call", "name": tc.name, "args": tc.args}

                result = self.registry.dispatch(tc.name, tc.args, working_dir=self.working_dir)

                # Truncate oversized results
                if len(result) > MAX_TOOL_RESULT_CHARS:
                    original_len = len(result)
                    result = (
                        result[:MAX_TOOL_RESULT_CHARS]
                        + f"\n\n[Truncated: tool response was {original_len:,} chars, "
                        f"exceeding the {MAX_TOOL_RESULT_CHARS:,} char limit]"
                    )

                yield {"type": "tool_result", "name": tc.name, "result": result}

                # Auto-error recovery: detect stderr in terminal results
                if tc.name == "terminal":
                    try:
                        parsed_result = json.loads(result)
                        stderr = parsed_result.get("stderr", "")
                        exit_code = parsed_result.get("exit_code", 0)
                        if stderr and exit_code != 0:
                            yield {"type": "self_correcting", "error": stderr.strip()}
                    except (json.JSONDecodeError, TypeError):
                        pass

                tool_msg = {
                    "role": "tool",
                    "content": result,
                    "tool_call_id": tc.id,
                    "timestamp": _now(),
                }
                messages.append(tool_msg)
                history.append(tool_msg)

            iteration += 1

        else:
            # Max iterations reached -- force summary
            summary = await self._force_summary(messages)
            history.append({"role": "assistant", "content": summary})
            yield {"type": "response", "content": summary}

    def _get_budget_warning(self, iteration: int) -> str | None:
        if self.max_iterations <= 0:
            return None
        progress = iteration / self.max_iterations

        if progress >= 0.9:
            remaining = self.max_iterations - iteration
            return (
                f"[BUDGET WARNING: Iteration {iteration}/{self.max_iterations}. "
                f"Only {remaining} iteration(s) left. "
                "Provide your final response NOW. No more tool calls unless absolutely critical.]"
            )
        if progress >= 0.7:
            remaining = self.max_iterations - iteration
            return (
                f"[BUDGET: Iteration {iteration}/{self.max_iterations}. "
                f"{remaining} iterations left. Start consolidating your work.]"
            )
        return None

    async def _force_summary(self, messages: list[dict]) -> str:
        summary_request = (
            "You've reached the maximum number of tool-calling iterations. "
            "Provide a final response summarizing what you've accomplished so far."
        )
        messages.append({"role": "user", "content": summary_request})

        response = await self.adapter.chat(messages, tools=None)
        self._total_tokens += response.usage.total_tokens
        return response.content or "Max iterations reached."
