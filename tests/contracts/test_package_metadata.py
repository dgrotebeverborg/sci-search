from importlib.metadata import entry_points, version


def test_installed_distribution_exposes_cli():
    assert version("sci-search")
    scripts = {item.name: item.value for item in entry_points(group="console_scripts")}
    assert scripts["sci-search"] == "sci_search.cli:main"
