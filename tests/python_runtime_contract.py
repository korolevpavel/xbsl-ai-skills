DIRECT_PYTHON_SKILLS = frozenset(
    {
        "xbsl-access-set",
        "xbsl-deploy",
        "xbsl-explore",
        "xbsl-file-add",
        "xbsl-form-add",
        "xbsl-form-cards",
        "xbsl-form-dashboard",
        "xbsl-form-info",
        "xbsl-image-add",
        "xbsl-lib-connect",
        "xbsl-meta-add",
        "xbsl-pattern-register",
        "xbsl-pattern-rls",
        "xbsl-rename",
        "xbsl-subsystem-add",
        "xbsl-uuid",
        "xbsl-validate",
    }
)

PYTHON_RUNTIME_LABEL = "Python 3.10+"
LAUNCHER_INSTRUCTION = (
    "Во всех командах ниже `{python}` означает `python` в Windows и `python3` в "
    "macOS/Linux/WSL. Выбирай команду сразу по текущей ОС, не запускай оба варианта."
)
VERSIONED_LAUNCHER_INSTRUCTION = (
    "Во всех командах ниже `{python}` означает `python` в Windows и `python3` в "
    "macOS/Linux/WSL. Выбранный интерпретатор должен быть Python 3.10+; если "
    "сомневаешься, проверь через `{python} --version`. Выбирай команду сразу "
    "по текущей ОС, не запускай оба варианта."
)
