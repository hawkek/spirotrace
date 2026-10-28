import spirotrace
from spirotrace import cli


def test_version_is_set():
    assert spirotrace.__version__ == "0.0.1"


def test_cli_without_command_prints_help(capsys):
    assert cli.main([]) == 0
    assert "usage" in capsys.readouterr().out


def test_unimplemented_command_says_so(capsys):
    assert cli.main(["template"]) == 1
    assert "not implemented" in capsys.readouterr().out


def test_run_without_settings_is_a_settings_error(tmp_path, capsys):
    assert cli.main(["run", "--project", str(tmp_path)]) == 2
    assert "spiro.toml" in capsys.readouterr().out
