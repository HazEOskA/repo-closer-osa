# Architecture Lock v0.2

Repo Closer jest samodzielnym produktem: własne repo, API, Run, state machine, persistence, permissions i deploy.

Controlled reuse dotyczy kodu/wzorców, nie współdzielonego runtime.

## Hard gates

1. LLM nie ma poświadczeń do GitHub/GCP.
2. Controller jako jedyny zmienia RunState.
3. Fix approval wiąże run/repo/SHA/plan/scope/commands.
4. PR approval wiąże konkretny diff hash i work branch.
5. Deploy approval wiąże konkretny obraz/digest + projekt/region/service.
6. Zmiana diffu po feedback loop wymaga ponownej zgody PR i nowego buildu/deploy approval.
7. Repo content jest niezaufany i nie może zmienić policy/capabilities.
8. `allowed_commands` jest dokładnym argv allowlist; `shell=False`.
9. Brak dowodu = UNKNOWN/BLOCKED, nie SUCCESS.
10. Full E2E nie zależy od OSA Agent / bounty runtime.
