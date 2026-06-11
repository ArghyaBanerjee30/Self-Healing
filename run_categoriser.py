"""
Run the categoriser agent against the four spec demo scenarios.

Usage:
    python run_categoriser.py
"""
import asyncio

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from core.signal import Signal, SignalSource
from core.incident import IncidentPath, IncidentConfidence
from categoriser import stage1 as s1
from categoriser.domain import CategoryResult
from categoriser.router import route

console = Console()

DEMO_SIGNALS = [
    {
        "label": "Demo 1 — TypeError (payments.py)",
        "signal": Signal(
            source=SignalSource.APPLICATION_LOG,
            service="payments",
            error_type="TypeError",
            stack_trace=(
                "Traceback (most recent call last):\n"
                '  File "/app/demo_app/payments.py", line 18, in process_payment\n'
                '    return order["items"][0]\n'
                "TypeError: 'NoneType' object is not subscriptable"
            ),
            project_id="project-x",
        ),
    },
    {
        "label": "Demo 2 — ZeroDivisionError (inventory.py)",
        "signal": Signal(
            source=SignalSource.APPLICATION_LOG,
            service="inventory",
            error_type="ZeroDivisionError",
            stack_trace=(
                "Traceback (most recent call last):\n"
                '  File "/app/demo_app/inventory.py", line 22, in get_unit_price\n'
                "    return total / quantity\n"
                "ZeroDivisionError: division by zero"
            ),
            project_id="project-x",
        ),
    },
    {
        "label": "Demo 3 — CrashLoopBackOff (payments pod)",
        "signal": Signal(
            source=SignalSource.KUBERNETES_EVENT,
            service="payments",
            error_type="CrashLoopBackOff",
            pod_name="payments-abc-123",
            pod_status="CrashLoopBackOff",
            restart_count=8,
            project_id="project-x",
        ),
    },
    {
        "label": "Demo 4 — ConnectionError (ambiguous: trace + pod restarting)",
        "signal": Signal(
            source=SignalSource.APPLICATION_LOG,
            service="payments",
            error_type="ConnectionError",
            stack_trace=(
                "Traceback (most recent call last):\n"
                '  File "/app/demo_app/payments.py", line 45, in charge\n'
                "    db.connect()\n"
                "ConnectionError: database unreachable"
            ),
            pod_name="db-xyz-456",
            pod_status="CrashLoopBackOff",
            restart_count=12,
            project_id="project-x",
        ),
    },
]

PATH_STYLE = {
    IncidentPath.CODE: "bold green",
    IncidentPath.INFRA: "bold yellow",
    IncidentPath.BOTH: "bold magenta",
    IncidentPath.TRANSIENT: "dim",
}

CONFIDENCE_STYLE = {
    IncidentConfidence.HIGH: "green",
    IncidentConfidence.LOW: "yellow",
}


def _seed_past_transient(sig: Signal, n: int = 4) -> None:
    """Push the occurrence counter past the transient gate so the demo doesn't wait 5 min."""
    for _ in range(n):
        s1._is_transient(sig)


def _render_result(label: str, sig: Signal, result: CategoryResult) -> None:
    path = result.incident.path
    confidence = result.incident.confidence
    stage = "Stage 2 (ambiguous)" if result.stage2 else "Stage 1 (unambiguous)"

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    table.add_column("key", style="dim", width=18)
    table.add_column("value")

    table.add_row("service", sig.service)
    table.add_row("error_type", sig.error_type)
    table.add_row("source", sig.source.value)
    table.add_row(
        "path",
        f"[{PATH_STYLE[path]}]{path.value.upper()}[/{PATH_STYLE[path]}]",
    )
    table.add_row(
        "confidence",
        f"[{CONFIDENCE_STYLE[confidence]}]{confidence.value}[/{CONFIDENCE_STYLE[confidence]}]",
    )
    table.add_row("resolved via", stage)

    if result.stage2:
        table.add_row(
            "stage2 scores",
            f"code={result.stage2.code_suspicion_score:.2f}  "
            f"infra={result.stage2.infra_suspicion_score:.2f}",
        )

    table.add_row("incident id", result.incident.id[:8] + "…")

    console.print(Panel(table, title=f"[bold]{label}[/bold]", border_style="blue"))


async def main() -> None:
    console.rule("[bold blue]Categoriser Agent — Demo Run[/bold blue]")
    console.print()

    for demo in DEMO_SIGNALS:
        sig: Signal = demo["signal"]
        label: str = demo["label"]

        # Seed occurrence counter so transient gate doesn't block the demo.
        _seed_past_transient(sig)

        with console.status(f"[dim]routing {sig.error_type}…[/dim]"):
            result = await route(sig)

        _render_result(label, sig, result)

    console.rule("[bold green]Done[/bold green]")


if __name__ == "__main__":
    asyncio.run(main())
