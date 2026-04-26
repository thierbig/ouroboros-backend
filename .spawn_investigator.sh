#!/usr/bin/env bash
# Launcher for investigator teammate in ouroboros-agent-quality team.
# Always drops into an interactive shell on exit so errors stay visible.
cd /c/Users/thier/ouroboros-backend || { echo "cd failed"; exec bash -i; }
echo "[spawn] starting claude.exe for investigator teammate..."
env CLAUDECODE=1 CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 \
  /c/Users/thier/AppData/Local/Microsoft/WinGet/Packages/Anthropic.ClaudeCode_Microsoft.Winget.Source_8wekyb3d8bbwe/claude.exe \
  --agent-id investigator@ouroboros-agent-quality \
  --agent-name investigator \
  --team-name ouroboros-agent-quality \
  --agent-color red \
  --parent-session-id 4e8729ab-d9ec-4af4-a713-f129a39a6ff1 \
  --agent-type general-purpose \
  --model opus
echo "[spawn] claude.exe exited with code $?"
exec bash -i
