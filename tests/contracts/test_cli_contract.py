from sci_search.cli import main


def test_cli_requires_corpus_and_exposes_supported_commands(capsys):
    try:
        main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0

    output = capsys.readouterr().out
    assert "--corpus" in output
    for command in ("investigate", "research-online", "serve", "evaluate-discovery"):
        assert command in output
