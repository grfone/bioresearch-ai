"""
Behavioural baseline for the BioResearch AI workspace FSM.

This script records the EXACT observable behaviour of the current
FSM implementation (transition table, entity mutators, orchestrator
actions) so that the LangGraph migration can be proven
behaviour-preserving by diffing the two JSON reports.

Run it from the repository root:

    PYTHONPATH=. .venv/bin/python scripts/fsm_behaviour_snapshot.py

It writes ``runtime/fsm-baseline.json`` (path overridable with
``--out``). The report is a deterministic, side-effect-free
description of what the FSM does — states, legal actions, resolved
targets, audit trails and error payloads.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.enums.workspace_state import (  # noqa: E402
    TRANSITIONS,
    WorkspaceAction,
    WorkspaceState,
    allowed_actions,
    next_state,
)
from app.core.exceptions import IllegalWorkspaceActionError  # noqa: E402
from app.domain.entities.paper import Paper  # noqa: E402
from app.domain.entities.research_question import ResearchQuestion  # noqa: E402
from app.domain.entities.research_session import ResearchSession  # noqa: E402


def _paper(pmid: str) -> Paper:
    return Paper(pmid=pmid, title=f"Paper {pmid}", abstract="abs")


def _session(state: WorkspaceState, **kw: Any) -> ResearchSession:
    return ResearchSession(
        question=ResearchQuestion(question="q"),
        state=state,
        **kw,
    )


def snapshot() -> dict[str, Any]:
    report: dict[str, Any] = {}

    # --- 1. The transition table itself. ---------------------------
    table: dict[str, dict[str, str]] = {}
    for state, actions in TRANSITIONS.items():
        table[state.value] = {}
        for action, target in actions.items():
            if callable(target):
                table[state.value][action.value] = "CALLABLE"
            else:
                table[state.value][action.value] = target.value
    report["transitions"] = table

    # --- 2. Legal actions per state. ------------------------------
    report["allowed_actions"] = {
        state.value: [a.value for a in allowed_actions(state)]
        for state in WorkspaceState
    }

    # --- 3. Resolved target for every (state, action) pair. -------
    resolved: dict[str, str] = {}
    errors: dict[str, Any] = {}
    for state in WorkspaceState:
        for action in WorkspaceAction:
            key = f"{state.value}+{action.value}"
            try:
                resolved[key] = next_state(state, action).value
            except IllegalWorkspaceActionError as exc:
                errors[key] = {
                    "current_state": exc.current_state,
                    "action": exc.action,
                    "allowed": sorted(exc.allowed),
                }  # type: ignore[assignment]
            except TypeError as exc:
                errors[key] = f"TypeError: {exc}"  # type: ignore[assignment]
    report["resolved_targets"] = resolved
    report["rejected_actions"] = errors

    # --- 4. The session-aware RETRY resolver. ---------------------
    retry_cases: dict[str, str] = {}
    for last_known in (None, WorkspaceState.INITIAL, WorkspaceState.INTERMEDIATE):
        for with_papers in (False, True):
            s = _session(WorkspaceState.ERROR, last_known_state=last_known)
            if with_papers:
                s.add_papers([_paper("1")])
            label = f"last_known={last_known.value if last_known else None},papers={with_papers}"
            s.transition_to(WorkspaceAction.RETRY)
            retry_cases[label] = s.state.value
    report["retry_resolution"] = retry_cases

    # --- 5. Audit trail shape. ------------------------------------
    s = _session(WorkspaceState.INITIAL)
    s.transition_to(WorkspaceAction.SEARCH)
    s.force_state(WorkspaceState.INTERMEDIATE, reason="Search returned 5 papers")
    report["audit_trail"] = [
        {
            "from": t.from_state.value,
            "to": t.to_state.value,
            "action": t.action.value if t.action else None,
            "reason": t.reason,
        }
        for t in s.state_history
    ]

    # --- 6. force_state legality. ---------------------------------
    force_cases: dict[str, str] = {}
    for state in WorkspaceState:
        for target in WorkspaceState:
            key = f"{state.value}->{target.value}"
            s = _session(state)
            try:
                s.force_state(target, reason="probe")
                force_cases[key] = "OK"
            except IllegalWorkspaceActionError as exc:
                force_cases[key] = f"REJECTED:{exc.action}"
    report["force_state"] = force_cases

    # --- 7. Corpus mutations move the state. ----------------------
    s = _session(WorkspaceState.INITIAL)
    s.add_papers([_paper("9")])
    report["add_papers_advances"] = s.state.value
    s.remove_paper("9")
    report["remove_paper_regresses"] = s.state.value

    # --- 8. Page / terminal projections. --------------------------
    report["pages"] = {st.value: st.page for st in WorkspaceState}
    report["is_terminal"] = {st.value: st.is_terminal for st in WorkspaceState}
    report["progress"] = {
        st.value: _session(st).progress for st in WorkspaceState
    }

    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=str(Path("runtime/fsm-baseline.json")),
        help="where to write the JSON report",
    )
    args = parser.parse_args()

    report = snapshot()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    out.write_text(payload)
    print(f"wrote {out} ({len(payload)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
