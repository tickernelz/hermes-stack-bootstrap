"""Tiny Rich/prompt_toolkit TUI facade."""

from __future__ import annotations

import sys
from typing import Sequence

from .hermes_discovery import HermesRuntime


class TuiDependencyError(RuntimeError):
    """Raised when interactive TUI dependencies are unavailable."""


class RichPromptTui:
    """Small TUI facade backed by Rich output and prompt_toolkit input."""

    def __init__(self) -> None:
        try:
            from prompt_toolkit import prompt as toolkit_prompt  # type: ignore
            from prompt_toolkit.completion import WordCompleter  # type: ignore
            from prompt_toolkit.shortcuts import checkboxlist_dialog  # type: ignore
            from rich.console import Console  # type: ignore
            from rich.panel import Panel  # type: ignore
            from rich.table import Table  # type: ignore
        except ImportError as exc:  # pragma: no cover - environment dependent
            manual = f"{sys.executable} -m pip install 'PyYAML>=6' 'rich>=13' 'prompt_toolkit>=3'"
            raise TuiDependencyError(
                "Interactive install requires TUI dependencies: rich and prompt_toolkit. "
                "The install.sh bootstrapper installs them automatically. "
                f"If you run the Python module directly, install them manually with: {manual}"
            ) from exc
        self._prompt = toolkit_prompt
        self._word_completer = WordCompleter
        self._checkboxlist_dialog = checkboxlist_dialog
        self.console = Console()
        self._panel = Panel
        self._table = Table

    def banner(self, title: str, subtitle: str) -> None:
        self.console.print(self._panel(subtitle, title=title, border_style="cyan"))

    def step(self, title: str) -> None:
        self.console.print(f"\n[bold cyan]{title}[/bold cyan]")

    def text(self, prompt: str, default: str = "") -> str:
        suffix = f" [{default}]" if default else ""
        value = self._prompt(f"{prompt}{suffix}: ").strip()
        return value or default

    def password(self, prompt: str) -> str:
        return self._prompt(f"{prompt}: ", is_password=True).strip()

    def confirm(self, prompt: str, default: bool = False) -> bool:
        suffix = "Y/n" if default else "y/N"
        while True:
            answer = self._prompt(f"{prompt} [{suffix}] ").strip().lower()
            if not answer:
                return default
            if answer in {"y", "yes"}:
                return True
            if answer in {"n", "no"}:
                return False
            self.console.print("[yellow]Please answer yes or no.[/yellow]")

    def select(self, prompt: str, choices: Sequence[str], default: str = "") -> str:
        choices = tuple(choices)
        if not choices:
            return default
        default = default if default in choices else choices[0]
        table = self._table.grid(padding=(0, 2))
        table.add_column(justify="right")
        table.add_column()
        for index, choice in enumerate(choices, start=1):
            marker = "*" if choice == default else " "
            table.add_row(f"{index}.", f"{marker} {choice}")
        self.console.print(prompt)
        self.console.print(table)
        completer = self._word_completer(list(choices), ignore_case=True)
        while True:
            answer = self._prompt(f"Select [{default}]: ", completer=completer).strip()
            if not answer:
                return default
            if answer.isdigit() and 1 <= int(answer) <= len(choices):
                return choices[int(answer) - 1]
            for choice in choices:
                if answer.lower() == choice.lower():
                    return choice
            self.console.print(f"[yellow]Choose one of: {', '.join(choices)}[/yellow]")

    def multi_select(self, prompt: str, choices: Sequence[str], defaults: Sequence[str] = ()) -> tuple[str, ...]:
        choices = tuple(choices)
        if not choices:
            return tuple(defaults)
        defaults = tuple(choice for choice in defaults if choice in choices)
        result = self._checkboxlist_dialog(
            title=prompt,
            text="Use Space to toggle, Enter to continue.",
            values=[(choice, choice) for choice in choices],
            default_values=list(defaults),
        ).run()
        selected = tuple(result or ())
        return selected or defaults or (choices[0],)

    def status(self, message: str):
        return self.console.status(message, spinner="dots")

    def runtime_summary(self, runtime: HermesRuntime) -> None:
        table = self._table(title="Detected Hermes runtime", show_header=False)
        table.add_column("Field", style="cyan")
        table.add_column("Value")
        table.add_row("Hermes CLI", f"{runtime.hermes_bin or 'not found'} ({runtime.hermes_bin_source})")
        table.add_row("Hermes Python", f"{runtime.hermes_python or 'not found'} ({runtime.hermes_python_source})")
        self.console.print(table)


def create_tui() -> RichPromptTui:
    return RichPromptTui()
