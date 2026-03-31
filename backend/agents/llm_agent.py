import asyncio
import json
import logging
import openai
from ..game.state import GameState
from ..game.serializer import serialize
from ..game.pathfinder import find_path, get_reachable

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an AI agent playing a 1v1 Bomberman game. Your goal is to score points by
destroying brick blocks with bombs. You win by:
  1. Having more bricks destroyed than your opponent when all bricks are gone
  2. Killing your opponent with a bomb (instant win)
  3. Having more points when the 3-minute timer expires

You receive the game state as text and must respond with a single JSON line choosing
your next action. Be strategic: farm bricks efficiently, avoid your own explosions,
and consider going for a kill if you are losing and cannot win on bricks alone.
Keep your reasoning to one concise sentence."""


class LLMAgent:
    def __init__(self, player_id: str, state_ref: list, action_queue: asyncio.Queue, client):
        self.player_id = player_id
        self.state_ref = state_ref        # mutable list holding current GameState
        self.action_queue = action_queue
        self.client = client
        self.last_prompt_tick = -1
        self.running = True

    async def run(self):
        while self.running:
            state: GameState = self.state_ref[0]

            if state.game_over:
                break

            if not state.players[self.player_id].alive:
                break

            # Only re-prompt if state has meaningfully changed
            if not self._should_reprompt(state):
                await asyncio.sleep(0.05)
                continue

            prompt = serialize(state, self.player_id)
            prompt_tick = state.tick
            self.last_prompt_tick = state.tick

            try:
                action = await asyncio.wait_for(
                    self._call_llm(prompt),
                    timeout=10.0
                )
            except asyncio.TimeoutError:
                logger.warning("[%s] LLM call timed out (10s)", self.player_id)
                action = {"action": "wait", "reasoning": "timeout"}
            except Exception as e:
                logger.error("[%s] LLM call failed: %s", self.player_id, e, exc_info=True)
                action = {"action": "wait", "reasoning": f"error: {e}"}

            # Ignore stale responses (older than 15 ticks)
            current_tick = self.state_ref[0].tick
            if current_tick - prompt_tick > 15:
                continue

            if action:
                await self.action_queue.put(action)

    def _should_reprompt(self, state: GameState) -> bool:
        """
        Re-prompt if:
        - Action queue is empty (agent has nothing queued)
        - AND at least one of:
          a. 10+ ticks elapsed since last prompt
          b. First prompt (last_prompt_tick == -1)
        """
        if not self.action_queue.empty():
            return False
        ticks_since = state.tick - self.last_prompt_tick
        return ticks_since >= 10 or self.last_prompt_tick == -1

    async def _call_llm(self, prompt: str) -> dict:
        logger.info("[%s] Sending LLM request (model: %s)", self.player_id, "openai/gpt-5.4")
        response = await self.client.chat.completions.create(
            model="openai/gpt-5.4",
            max_tokens=2048,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )
        content = response.choices[0].message.content
        if not content:
            logger.warning("[%s] LLM returned empty/null content. Full response: %s", self.player_id, response)
            return {"action": "wait", "reasoning": "empty response from model"}
        text = content.strip()
        logger.info("[%s] LLM raw response: %s", self.player_id, text[:200])
        # Extract JSON — handle cases where model adds extra text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start == -1 or end == 0:
            logger.warning("[%s] No JSON found in response: %s", self.player_id, text[:200])
            return {"action": "wait", "reasoning": "parse error"}
        parsed = json.loads(text[start:end])
        logger.info("[%s] Parsed action: %s", self.player_id, parsed)
        # Validate action field
        valid_actions = {"move", "move_and_bomb", "bomb_here", "wait"}
        if parsed.get("action") not in valid_actions:
            logger.warning("[%s] Invalid action '%s', defaulting to wait", self.player_id, parsed.get("action"))
            parsed["action"] = "wait"
        return parsed

    def stop(self):
        self.running = False
