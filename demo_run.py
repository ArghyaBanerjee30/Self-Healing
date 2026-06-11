"""
Demo runner — shows the skill-based supervisor in action.

Usage:
    python demo_run.py                   # runs all 4 demo scenarios
    python demo_run.py demo-001          # runs a specific scenario
    python demo_run.py --list            # lists available scenarios
"""
import sys
from categoriser.mock_classifier import get_classified_log, list_scenarios, DEMO_SCENARIOS
from core.incident import Incident
from agents.supervisor import Supervisor


def run_scenario(incident_id: str) -> None:
    classified = get_classified_log(incident_id)
    incident = Incident.from_signal(
        incident_id=classified.incident_id,
        signal=classified.signal,
        category=classified.category,
    )
    print(f"\n{'#'*60}")
    print(f"SCENARIO: {incident_id}")
    print(f"Classification: {classified.category.value.upper()} "
          f"(confidence={classified.confidence.value})")
    print(f"Reason: {classified.classification_reason}")
    print(f"{'#'*60}")

    # Supervisor loads the skill, calls LLM, creates TodoList, runs subagents
    supervisor = Supervisor(verbose=True)
    supervisor.run(incident)


def main() -> None:
    args = sys.argv[1:]

    if "--list" in args:
        print("\nAvailable demo scenarios:\n")
        for s in list_scenarios():
            print(f"  {s['incident_id']}  [{s['category'].upper()}]  "
                  f"{s['error_type']} in {s['service']}")
            print(f"    {s['reason']}\n")
        return

    if args:
        run_scenario(args[0])
    else:
        for incident_id in DEMO_SCENARIOS:
            run_scenario(incident_id)
            print()


if __name__ == "__main__":
    main()
