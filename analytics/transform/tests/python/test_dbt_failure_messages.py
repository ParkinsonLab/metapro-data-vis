from transform.lib.dbt_failure_messages import format_dbt_failure_message


def test_format_dbt_failure_message_derives_assertion_name_from_generic_row_count():
    message = format_dbt_failure_message(
        unique_id="test.rpkm_transform.assert_mart_nonempty",
        message="Got 1 result, configured to fail if != 0",
    )
    assert message == "Assertion failed: assert_mart_nonempty"


def test_format_dbt_failure_message_preserves_model_runtime_errors():
    message = format_dbt_failure_message(
        unique_id="model.rpkm_transform.int_rpkm_by_ec_tax",
        message=(
            "Runtime Error in model int_rpkm_by_ec_tax\n"
            "  Invalid Input Error: RPKM file is empty"
        ),
    )
    assert message == "RPKM file is empty"


def test_format_dbt_failure_message_keeps_specific_test_detail_when_present():
    message = format_dbt_failure_message(
        unique_id="test.rpkm_transform.some_custom_test",
        message="expected 5 rows, got 3",
    )
    assert message == "some_custom_test: expected 5 rows, got 3"
