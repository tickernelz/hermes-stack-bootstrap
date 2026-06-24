class FakeTui:
    def __init__(self, answers):
        self.answers = list(answers)
        self.events = []

    def _pop(self):
        if not self.answers:
            raise AssertionError("FakeTui ran out of answers")
        return self.answers.pop(0)

    def banner(self, title: str, subtitle: str) -> None:
        self.events.append(("banner", title, subtitle))

    def step(self, title: str) -> None:
        self.events.append(("step", title))

    def text(self, prompt: str, default: str = "") -> str:
        self.events.append(("text", prompt, default))
        answer = self._pop()
        return default if answer is None else answer

    def confirm(self, prompt: str, default: bool = False) -> bool:
        self.events.append(("confirm", prompt, default))
        answer = self._pop()
        return default if answer is None else bool(answer)

    def select(self, prompt: str, choices, default: str = "") -> str:
        self.events.append(("select", prompt, tuple(choices), default))
        answer = self._pop()
        return default if answer is None else answer

    def multi_select(self, prompt: str, choices, defaults=()):
        self.events.append(("multi_select", prompt, tuple(choices), tuple(defaults)))
        answer = self._pop()
        return tuple(defaults) if answer is None else tuple(answer)

    def password(self, prompt: str) -> str:
        self.events.append(("password", prompt))
        return self._pop()

    def status(self, message: str):
        events = self.events

        class StatusRecorder:
            def __enter__(self):
                events.append(("status_start", message))

            def __exit__(self, exc_type, exc, tb):
                events.append(("status_stop", message))
                return False

        return StatusRecorder()

    def runtime_summary(self, runtime) -> None:
        self.events.append(("runtime", runtime.hermes_bin, runtime.hermes_python))
