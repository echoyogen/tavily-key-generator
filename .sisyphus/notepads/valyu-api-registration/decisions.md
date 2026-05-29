# Decisions

## 2026-05-29 Session ses_18da4286bffeE2iF2yT8xz44Ig

### Architecture: Option A
- `register()` fully inline (not using `super().register()`)
- All abstract methods stub `raise NotImplementedError`
- Browser code ONLY in `_browser_fallback()`

### Parallelization Plan
- Wave 1: Task 1 alone (scaffold)
- Wave 2: Tasks 2, 3, 4, 5 in parallel (each fills different methods in the scaffold)
- Wave 3: Tasks 6 + 7 in parallel (Task 6 wires register(); Task 7 writes tests)
- Wave Final: F1-F4 in parallel

### Test Strategy
- Delete `test_valyu_wait_strategy.py` (tests deprecated browser behavior)
- New `test_valyu_service.py` with 4 test classes, 10+ test methods
- All tests use mocks, no real network calls
