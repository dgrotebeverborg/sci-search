"""Explicit portable replay modules and their transitive local dependencies."""

# Only replay entry points are included: derived_outputs.prepare_jobs uses application
# coverage code, while its offline compute entry point needs only calculations.
ENGINE_MANIFEST = {
    "calculations.py": (),
    "cbs_odata.py": (),
    "tabular.py": ("calculations.py",),
    "packages.py": (
        "tabular.py",
        "cbs_odata.py",
        "spreadsheets.py",
        "statistical_tables.py",
        "jsonstat.py",
        "owid_tables.py",
        "preparation.py",
    ),
    "preparation.py": ("tabular.py", "daily.py", "statistical_tables.py"),
    "spreadsheets.py": (),
    "statistical_tables.py": (),
    "jsonstat.py": (),
    "owid_tables.py": (),
    "daily.py": ("tabular.py",),
    "wildfire.py": (),
    "python_rows.py": ("tabular.py",),
    "verification.py": ("statistical_tables.py", "tabular.py"),
    "derived_outputs.py": ("calculations.py",),
}
SOURCE_ENTRY_POINTS = (
    "tabular.py",
    "packages.py",
    "preparation.py",
    "wildfire.py",
    "python_rows.py",
    "verification.py",
)


def engine_modules(*entry_points):
    """Return one deterministic closure for source, derived and legacy packaging."""
    required = set()

    def include(name):
        if name not in required:
            required.add(name)
            for dependency in ENGINE_MANIFEST[name]:
                include(dependency)

    for name in entry_points:
        include(name)
    return tuple(sorted(required))
