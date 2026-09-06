# Architecture Lock — Slice 1

CREATED → MAPPING → AUDITING → PLANNING → AWAITING_FIX_APPROVAL

- standalone backend/domain/lifecycle;
- analizowane repo przypięte do pełnego SHA;
- GitHub adapter w Slice 1 implementuje wyłącznie GET;
- brak clone, exec, push, PR, merge i deploy do analizowanego repo;
- README/kod/workflow są niezaufanymi danymi;
- tylko Controller może zmieniać stan Run;
- wynik końcowy to AWAITING_FIX_APPROVAL.
