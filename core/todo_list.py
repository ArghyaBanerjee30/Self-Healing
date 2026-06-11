from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime


class TodoStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass
class TodoItem:
    index: int
    description: str
    assigned_to: str               # which subagent owns this
    status: TodoStatus = TodoStatus.PENDING
    result: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def start(self) -> None:
        self.status = TodoStatus.IN_PROGRESS
        self.started_at = datetime.utcnow()

    def complete(self, result: str) -> None:
        self.status = TodoStatus.DONE
        self.result = result
        self.completed_at = datetime.utcnow()

    def fail(self, reason: str) -> None:
        self.status = TodoStatus.FAILED
        self.result = reason
        self.completed_at = datetime.utcnow()

    def block(self, reason: str) -> None:
        self.status = TodoStatus.BLOCKED
        self.result = reason


@dataclass
class TodoList:
    incident_id: str
    items: list[TodoItem] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def add(self, description: str, assigned_to: str) -> int:
        idx = len(self.items)
        self.items.append(TodoItem(index=idx, description=description, assigned_to=assigned_to))
        return idx

    def get(self, index: int) -> TodoItem:
        return self.items[index]

    def pending(self) -> list[TodoItem]:
        return [i for i in self.items if i.status == TodoStatus.PENDING]

    def all_done(self) -> bool:
        return all(i.status in (TodoStatus.DONE, TodoStatus.FAILED) for i in self.items)

    def has_failures(self) -> bool:
        return any(i.status == TodoStatus.FAILED for i in self.items)

    def summary(self) -> str:
        done = sum(1 for i in self.items if i.status == TodoStatus.DONE)
        failed = sum(1 for i in self.items if i.status == TodoStatus.FAILED)
        blocked = sum(1 for i in self.items if i.status == TodoStatus.BLOCKED)
        total = len(self.items)
        return f"{done}/{total} done | {failed} failed | {blocked} blocked"

    def render(self) -> list[dict]:
        icons = {
            TodoStatus.PENDING: "○",
            TodoStatus.IN_PROGRESS: "◉",
            TodoStatus.DONE: "✓",
            TodoStatus.FAILED: "✗",
            TodoStatus.BLOCKED: "⊘",
        }
        return [
            {
                "index": item.index,
                "icon": icons[item.status],
                "description": item.description,
                "assigned_to": item.assigned_to,
                "status": item.status.value,
                "result": item.result,
            }
            for item in self.items
        ]

    def display(self) -> str:
        lines = [f"TodoList [{self.incident_id}]"]
        for row in self.render():
            lines.append(
                f"  {row['icon']} [{row['assigned_to']}] {row['description']}"
            )
            if row["result"]:
                lines.append(f"      └─ {row['result'][:120]}")
        lines.append(f"  {self.summary()}")
        return "\n".join(lines)
