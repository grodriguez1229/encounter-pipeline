from encounter_pipeline.npi import is_valid_npi, npi_check_digit


def test_cms_example_npi():
    # 1234567893 is the worked example in the CMS NPI check digit document.
    assert npi_check_digit("123456789") == 3
    assert is_valid_npi("1234567893")


def test_rejects_bad_check_digit_and_bad_format():
    assert not is_valid_npi("1234567890")
    assert not is_valid_npi("123456789")
    assert not is_valid_npi("12345678A3")
    assert not is_valid_npi("")
    assert not is_valid_npi(None)
