"""Enhanced fakeable TUI primitives for wizard v2."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Protocol, Sequence


class TuiDependencyError(RuntimeError):
    """Raised when interactive TUI dependencies are unavailable."""


@dataclass(frozen=True)
class Choice:
    """A selectable wizard choice.

    ``value`` is returned to callers. ``label`` and ``description`` are display-only.
    Flags influence styling and availability.
    """

    label: str
    value: Any | None = None
    description: str | None = None
    disabled: bool = False
    recommended: bool = False
    danger: bool = False

    def resolved_value(self) -> Any:
        return self.label if self.value is None else self.value


class WizardTui(Protocol):
    """Small wizard interface that can be replaced by a fake in tests."""

    def step(self, index: int, total: int, title: str, subtitle: str | None = None) -> None: ...
    def info(self, message: str) -> None: ...
    def warning(self, message: str) -> None: ...
    def select(self, prompt: str, choices: Sequence[Any], default: Any | None = None) -> Any: ...
    def multi_select(
        self, prompt: str, choices: Sequence[Any], defaults: Sequence[Any] | None = None
    ) -> tuple[Any, ...]: ...
    def confirm(self, prompt: str, default: bool = True) -> bool: ...
    def text(self, prompt: str, default: str | None = None, validate: Callable[[str], Any] | None = None) -> str: ...
    def password(self, prompt: str, env_name: str | None = None) -> str: ...
    def summary_table(self, title: str, rows: Sequence[Any]) -> None: ...
    def progress(self, label: str, current: int, total: int) -> None: ...
    def spinner(self, label: str): ...


def _choice(item: Any) -> Choice:
    if isinstance(item, Choice):
        return item
    if isinstance(item, dict):
        return Choice(
            label=str(item.get("label", item.get("value", ""))),
            value=item.get("value", item.get("label")),
            description=item.get("description"),
            disabled=bool(item.get("disabled", False)),
            recommended=bool(item.get("recommended", False)),
            danger=bool(item.get("danger", False)),
        )
    return Choice(label=str(item), value=item)


def _choices(items: Sequence[Any]) -> tuple[Choice, ...]:
    return tuple(_choice(item) for item in items)


def _same_value(left: Any, right: Any) -> bool:
    return left == right or str(left) == str(right)


def _default_choice(choices: Sequence[Choice], default: Any | None) -> Choice | None:
    enabled = [choice for choice in choices if not choice.disabled]
    if not enabled:
        return None
    if default is not None:
        for choice in enabled:
            if _same_value(choice.resolved_value(), default) or _same_value(choice.label, default):
                return choice
    for choice in enabled:
        if choice.recommended:
            return choice
    return enabled[0]


class ConsoleWizardTui:
    """No-dependency fallback TUI for non-rich environments."""

    def step(self, index: int, total: int, title: str, subtitle: str | None = None) -> None:
        print(f"\nHermes Stack Bootstrap Wizard\nStep {index}/{total}: {title}")
        if subtitle:
            print(subtitle)

    def info(self, message: str) -> None:
        print(message)

    def warning(self, message: str) -> None:
        print(f"Warning: {message}")

    def select(self, prompt: str, choices: Sequence[Any], default: Any | None = None) -> Any:
        choice_items = [choice for choice in _choices(choices) if not choice.disabled]
        default_choice = _default_choice(choice_items, default)
        if default_choice is None:
            raise ValueError("select requires at least one enabled choice")
        print(prompt)
        for i, choice in enumerate(choice_items, 1):
            mark = "*" if _same_value(choice.resolved_value(), default_choice.resolved_value()) else " "
            desc = f" — {choice.description}" if choice.description else ""
            print(f"  {i}. {mark} {choice.label}{desc}")
        ans = input(f"Select [{default_choice.label}]: ").strip()
        if not ans:
            return default_choice.resolved_value()
        if ans.isdigit() and 1 <= int(ans) <= len(choice_items):
            return choice_items[int(ans) - 1].resolved_value()
        for choice in choice_items:
            if ans.lower() in {choice.label.lower(), str(choice.resolved_value()).lower()}:
                return choice.resolved_value()
        return default_choice.resolved_value()

    def multi_select(
        self, prompt: str, choices: Sequence[Any], defaults: Sequence[Any] | None = None
    ) -> tuple[Any, ...]:
        choice_items = [choice for choice in _choices(choices) if not choice.disabled]
        defaults = tuple(defaults or ())
        default_values = [
            choice.resolved_value()
            for choice in choice_items
            if any(
                _same_value(choice.resolved_value(), default) or _same_value(choice.label, default)
                for default in defaults
            )
        ]
        print(prompt + " (comma numbers; Enter keeps defaults)")
        for i, choice in enumerate(choice_items, 1):
            mark = "*" if choice.resolved_value() in default_values else " "
            desc = f" — {choice.description}" if choice.description else ""
            print(f"  {i}. {mark} {choice.label}{desc}")
        ans = input("Select: ").strip()
        if not ans:
            return tuple(default_values)
        out = []
        for part in ans.split(","):
            part = part.strip()
            if part.isdigit() and 1 <= int(part) <= len(choice_items):
                out.append(choice_items[int(part) - 1].resolved_value())
        return tuple(out or default_values)

    def confirm(self, prompt: str, default: bool = True) -> bool:
        ans = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
        return default if not ans else ans.startswith("y")

    def text(self, prompt: str, default: str | None = None, validate: Callable[[str], Any] | None = None) -> str:
        while True:
            value = input(f"{prompt} [{default or ''}]: ").strip() or (default or "")
            if validate is None:
                return value
            verdict = validate(value)
            if verdict in (True, None):
                return value
            self.warning(str(verdict))

    def password(self, prompt: str, env_name: str | None = None) -> str:
        import getpass

        return getpass.getpass(f"{prompt}{f' ({env_name})' if env_name else ''}: ").strip()

    def summary_table(self, title: str, rows: Sequence[Any]) -> None:
        print(f"\n{title}")
        for row in rows:
            key, value = row[:2]
            print(f"  {key}: {value}")

    def progress(self, label: str, current: int, total: int) -> None:
        print(f"[{current}/{total}] {label}")

    @contextmanager
    def spinner(self, label: str):
        print(label)
        yield


class RichWizardTui:
    """Rich/prompt_toolkit implementation of the wizard v2 primitives."""

    def __init__(self, console: Any | None = None) -> None:
        try:
            from prompt_toolkit import prompt as toolkit_prompt  # type: ignore
            from prompt_toolkit.shortcuts import checkboxlist_dialog, radiolist_dialog  # type: ignore
            from rich.console import Console  # type: ignore
            from rich.panel import Panel  # type: ignore
            from rich.progress_bar import ProgressBar  # type: ignore
            from rich.style import Style  # type: ignore
            from rich.table import Table  # type: ignore
            from rich.text import Text  # type: ignore
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise TuiDependencyError("Wizard v2 requires rich>=13 and prompt_toolkit>=3") from exc
        self.console = console or Console()
        self._prompt = toolkit_prompt
        self._checkboxlist_dialog = checkboxlist_dialog
        self._radiolist_dialog = radiolist_dialog
        self._panel = Panel
        self._progress_bar = ProgressBar
        self._style = Style
        self._table = Table
        self._text = Text

    def step(self, index: int, total: int, title: str, subtitle: str | None = None) -> None:
        lines = ["Hermes Stack Bootstrap Wizard", f"Step {index}/{total}: {title}"]
        if subtitle:
            lines.append(subtitle)
        self.console.print(self._panel("\n".join(lines), border_style="cyan"))

    def info(self, message: str) -> None:
        self.console.print(self._panel(message, border_style="blue", title="Info"))

    def warning(self, message: str) -> None:
        self.console.print(self._panel(message, border_style="yellow", title="Warning"))

    def select(self, prompt: str, choices: Sequence[Any], default: Any | None = None) -> Any:
        choice_items = _choices(choices)
        default_choice = _default_choice(choice_items, default)
        if default_choice is None:
            raise ValueError("select requires at least one enabled choice")
        self._print_choices(prompt, choice_items, default_choice.resolved_value())
        values = [
            (choice.resolved_value(), self._choice_text(choice)) for choice in choice_items if not choice.disabled
        ]
        result = self._radiolist_dialog(
            title=prompt,
            text="Use arrows to move, Enter to choose.",
            values=values,
            default=default_choice.resolved_value(),
        ).run()
        return default_choice.resolved_value() if result is None else result

    def multi_select(
        self, prompt: str, choices: Sequence[Any], defaults: Sequence[Any] | None = None
    ) -> tuple[Any, ...]:
        choice_items = _choices(choices)
        enabled = [choice for choice in choice_items if not choice.disabled]
        if not enabled:
            return ()
        defaults = tuple(defaults or ())
        default_values = [
            choice.resolved_value()
            for choice in enabled
            if any(
                _same_value(choice.resolved_value(), default) or _same_value(choice.label, default)
                for default in defaults
            )
        ]
        self._print_choices(prompt, choice_items, None)
        result = self._checkboxlist_dialog(
            title=prompt,
            text="Use arrows to move, Space to toggle, Enter to continue.",
            values=[(choice.resolved_value(), self._choice_text(choice)) for choice in enabled],
            default_values=default_values,
        ).run()
        return tuple(result or ())

    def confirm(self, prompt: str, default: bool = True) -> bool:
        suffix = "Y/n" if default else "y/N"
        while True:
            value = self._prompt(f"{prompt} [{suffix}]: ").strip().lower()
            if not value:
                return default
            if value in {"y", "yes", "true", "1"}:
                return True
            if value in {"n", "no", "false", "0"}:
                return False
            self.warning("Please answer yes or no.")

    def text(self, prompt: str, default: str | None = None, validate: Callable[[str], Any] | None = None) -> str:
        suffix = f" [{default}]" if default is not None else ""
        while True:
            value = self._prompt(f"{prompt}{suffix}: ").strip()
            if not value and default is not None:
                value = default
            if validate is None:
                return value
            try:
                verdict = validate(value)
            except Exception as exc:  # noqa: BLE001 - validators may be simple functions
                self.warning(str(exc))
                continue
            if verdict is True or verdict is None:
                return value
            self.warning(str(verdict))

    def password(self, prompt: str, env_name: str | None = None) -> str:
        label = f"{prompt} ({env_name})" if env_name else prompt
        return self._prompt(f"{label}: ", is_password=True).strip()

    def summary_table(self, title: str, rows: Sequence[Any]) -> None:
        table = self._table(title=title, header_style="bold cyan")
        table.add_column("Item", style="cyan", no_wrap=True)
        table.add_column("Value")
        for row in rows:
            if isinstance(row, dict):
                key = row.get("key", row.get("label", row.get("name", "")))
                value = row.get("value", row.get("status", ""))
            else:
                key, value = row[:2]
            table.add_row(str(key), str(value))
        self.console.print(table)

    def progress(self, label: str, current: int, total: int) -> None:
        total = max(total, 1)
        current = min(max(current, 0), total)
        bar = self._progress_bar(total=total, completed=current, width=30)
        self.console.print(f"[cyan]{label}[/cyan] {bar} {current}/{total}")

    @contextmanager
    def spinner(self, label: str):
        with self.console.status(label, spinner="dots"):
            yield

    def _choice_text(self, choice: Choice) -> str:
        bits = [choice.label]
        if choice.recommended:
            bits.append("recommended")
        if choice.danger:
            bits.append("danger")
        if choice.description:
            bits.append(choice.description)
        return " — ".join(bits)

    def _choice_style(self, choice: Choice):
        if choice.disabled:
            return self._style(dim=True)
        if choice.danger:
            return self._style(color="red")
        if choice.recommended:
            return self._style(color="green")
        return self._style()

    def _print_choices(self, prompt: str, choices: Sequence[Choice], default: Any | None) -> None:
        table = self._table(title=prompt, show_header=True, header_style="bold cyan")
        table.add_column("", width=2)
        table.add_column("Choice")
        table.add_column("Description")
        for choice in choices:
            marker = "✓" if default is not None and _same_value(choice.resolved_value(), default) else ""
            badges = []
            if choice.recommended:
                badges.append("recommended")
            if choice.danger:
                badges.append("danger")
            if choice.disabled:
                badges.append("disabled")
            label = choice.label + (f" ({', '.join(badges)})" if badges else "")
            table.add_row(marker, label, choice.description or "", style=self._choice_style(choice))
        self.console.print(table)


class FakeWizardTui:
    """Deterministic fake for unit tests.

    Provide answer queues by primitive name, e.g. ``FakeWizardTui(select=["full"], confirm=[True])``.
    Calls are recorded in ``events``.
    """

    def __init__(self, **answers: Iterable[Any]) -> None:
        self.answers = {name: list(values) for name, values in answers.items()}
        self.events: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.events.append((name, args, kwargs))

    def _answer(self, name: str, fallback: Any = None) -> Any:
        queue = self.answers.get(name, [])
        return queue.pop(0) if queue else fallback

    def step(self, index: int, total: int, title: str, subtitle: str | None = None) -> None:
        self._record("step", index, total, title, subtitle)

    def info(self, message: str) -> None:
        self._record("info", message)

    def warning(self, message: str) -> None:
        self._record("warning", message)

    def select(self, prompt: str, choices: Sequence[Any], default: Any | None = None) -> Any:
        self._record("select", prompt, choices, default=default)
        choice_items = _choices(choices)
        default_choice = _default_choice(choice_items, default)
        fallback = default_choice.resolved_value() if default_choice else None
        return self._answer("select", fallback)

    def multi_select(
        self, prompt: str, choices: Sequence[Any], defaults: Sequence[Any] | None = None
    ) -> tuple[Any, ...]:
        self._record("multi_select", prompt, choices, defaults=defaults)
        fallback = tuple(defaults or ())
        answer = self._answer("multi_select", fallback)
        return tuple(answer or ())

    def confirm(self, prompt: str, default: bool = True) -> bool:
        self._record("confirm", prompt, default=default)
        return bool(self._answer("confirm", default))

    def text(self, prompt: str, default: str | None = None, validate: Callable[[str], Any] | None = None) -> str:
        self._record("text", prompt, default=default, validate=validate)
        value = str(self._answer("text", default or ""))
        if validate is not None:
            verdict = validate(value)
            if verdict not in (True, None):
                raise ValueError(str(verdict))
        return value

    def password(self, prompt: str, env_name: str | None = None) -> str:
        self._record("password", prompt, env_name=env_name)
        return str(self._answer("password", ""))

    def summary_table(self, title: str, rows: Sequence[Any]) -> None:
        self._record("summary_table", title, rows)

    def progress(self, label: str, current: int, total: int) -> None:
        self._record("progress", label, current, total)

    @contextmanager
    def spinner(self, label: str):
        self._record("spinner", label)
        yield


def create_tui(fake: bool = False, **answers: Iterable[Any]) -> WizardTui:
    """Create a wizard TUI; ``fake=True`` returns ``FakeWizardTui`` for tests."""

    if fake:
        return FakeWizardTui(**answers)
    try:
        return RichWizardTui()
    except TuiDependencyError:
        return ConsoleWizardTui()


__all__ = [
    "Choice",
    "ConsoleWizardTui",
    "FakeWizardTui",
    "RichWizardTui",
    "TuiDependencyError",
    "WizardTui",
    "create_tui",
]
