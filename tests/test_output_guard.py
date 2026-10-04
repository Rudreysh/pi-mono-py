from pi_mono.core.output_guard import restore_stdout, take_over_stdout


def test_take_over_stdout_redirects_output_to_stderr(capsys):
    take_over_stdout()
    try:
        print("unexpected stdout")
    finally:
        restore_stdout()

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "unexpected stdout\n"
