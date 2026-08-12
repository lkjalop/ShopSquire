from scripts.check_source_file_sizes import main


def test_no_new_source_file_exceeds_two_thousand_lines():
    assert main() == 0
