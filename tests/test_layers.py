import boto3
from click import UsageError
from moto import mock_aws
import pytest

from unittest.mock import ANY, call, MagicMock, patch

from newrelic_lambda_cli.layers import (
    _attach_license_key_policy,
    _detach_license_key_policy,
    _add_new_relic,
    _remove_new_relic,
    index,
    install,
    uninstall,
    layer_selection,
)
from newrelic_lambda_cli.utils import get_arn_prefix

from .conftest import layer_install, layer_uninstall


@mock_aws
def test_add_new_relic(aws_credentials, mock_function_config):
    session = boto3.Session(region_name="us-east-1")

    config = mock_function_config("python3.12")

    assert config["Configuration"]["Handler"] == "original_handler"

    update_kwargs = _add_new_relic(
        layer_install(
            session=session,
            aws_region="us-east-1",
            nr_account_id=12345,
            enable_extension=True,
            enable_extension_function_logs=True,
        ),
        config,
        nr_license_key=None,
    )

    assert update_kwargs["FunctionName"] == config["Configuration"]["FunctionArn"]
    assert update_kwargs["Handler"] == "newrelic_lambda_wrapper.handler"
    assert update_kwargs["Environment"]["Variables"]["NEW_RELIC_ACCOUNT_ID"] == "12345"
    assert (
        update_kwargs["Environment"]["Variables"]["NEW_RELIC_LAMBDA_HANDLER"]
        == config["Configuration"]["Handler"]
    )
    assert (
        update_kwargs["Environment"]["Variables"]["NEW_RELIC_LAMBDA_EXTENSION_ENABLED"]
        == "true"
    )
    assert (
        update_kwargs["Environment"]["Variables"][
            "NEW_RELIC_EXTENSION_SEND_FUNCTION_LOGS"
        ]
        == "false"
    )

    config = mock_function_config("not.a.runtime")
    assert (
        _add_new_relic(
            layer_install(
                session=session,
                aws_region="us-east-1",
                nr_account_id=12345,
                enable_extension=True,
                enable_extension_function_logs=True,
            ),
            config,
            nr_license_key=None,
        )
        is False
    )

    config = mock_function_config("python3.12")
    config["Configuration"]["Layers"] = [{"Arn": get_arn_prefix("us-east-1")}]
    assert (
        _add_new_relic(
            layer_install(
                session=session,
                aws_region="us-east-1",
                nr_account_id=12345,
                enable_extension=True,
                enable_extension_function_logs=True,
            ),
            config,
            nr_license_key=None,
        )
        is True
    )

    with patch("newrelic_lambda_cli.layers.index") as mock_index:
        mock_index.return_value = []
        config = mock_function_config("python3.12")
        assert (
            _add_new_relic(
                layer_install(
                    session=session,
                    aws_region="us-east-1",
                    nr_account_id=12345,
                    enable_extension=True,
                    enable_extension_function_logs=True,
                ),
                config,
                nr_license_key=None,
            )
            is False
        )

    with patch("newrelic_lambda_cli.layers.index") as mock_index:
        with patch(
            "newrelic_lambda_cli.layers.layer_selection"
        ) as layer_selection_mock:
            mock_index.return_value = [
                {
                    "LatestMatchingVersion": {
                        "LayerVersionArn": "arn:aws:lambda:us-east-1:123456789:layer/javajava"
                    }
                },
                {
                    "LatestMatchingVersion": {
                        "LayerVersionArn": "arn:aws:lambda:us-east-1:123456789:layer/NewRelicLambdaExtension"
                    }
                },
            ]
            layer_selection_mock.return_value = [
                "arn:aws:lambda:us-east-1:123456789:layer/NewRelicLambdaExtension"
            ]

            config = mock_function_config("java11")
            _add_new_relic(
                layer_install(
                    session=session,
                    aws_region="us-east-1",
                    nr_account_id=12345,
                    enable_extension=True,
                    enable_extension_function_logs=True,
                ),
                config,
                nr_license_key=None,
            )

            layer_selection_mock.assert_called_with(
                mock_index.return_value, "java11", "x86_64"
            )
            assert "original_handler" in config["Configuration"]["Handler"]

            # Java handler testing
            layer_selection_mock.return_value = [
                "arn:aws:lambda:us-east-1:123456789:layer/javajava"
            ]

            update_kwargs = _add_new_relic(
                layer_install(
                    session=session,
                    aws_region="us-east-1",
                    nr_account_id=12345,
                    enable_extension=True,
                    enable_extension_function_logs=True,
                ),
                config,
                nr_license_key=None,
            )
            assert (
                "com.newrelic.java.HandlerWrapper::handleRequest"
                in update_kwargs["Handler"]
            )
            assert (
                "original_handler"
                in update_kwargs["Environment"]["Variables"]["NEW_RELIC_LAMBDA_HANDLER"]
            )

    mock_layers = [
        {
            "LatestMatchingVersion": {
                "LayerVersionArn": "arn:aws:lambda:us-east-1:123456789:layer/javajava"
            }
        },
        {
            "LatestMatchingVersion": {
                "LayerVersionArn": "arn:aws:lambda:us-east-1:123456789:layer/NewRelicLambdaExtension"
            }
        },
    ]

    with patch("newrelic_lambda_cli.layers.click.prompt") as mock_prompt, patch(
        "sys.stdout.isatty"
    ) as mock_isatty:
        mock_isatty.return_value = True
        mock_prompt.return_value = 0
        result = layer_selection(mock_layers, "python3.12", "x86_64")
        assert result == "arn:aws:lambda:us-east-1:123456789:layer/javajava"

    with patch("sys.stdout.isatty") as mock_isatty:
        mock_isatty.return_value = False
        with pytest.raises(UsageError):
            layer_selection(mock_layers, "python3.12", "x86_64")

    config = mock_function_config("python3.12")
    _add_new_relic(
        layer_install(
            session=session,
            aws_region="us-east-1",
            nr_account_id=12345,
            nr_region="staging",
            enable_extension=True,
            enable_extension_function_logs=True,
        ),
        config,
        "foobarbaz",
    )
    assert (
        "NEW_RELIC_TELEMETRY_ENDPOINT"
        in config["Configuration"]["Environment"]["Variables"]
    )

    config = mock_function_config("python3.12")
    config["Configuration"]["Environment"]["Variables"]["NEW_RELIC_FOO"] = "bar"
    config["Configuration"]["Layers"] = [{"Arn": get_arn_prefix("us-east-1")}]
    update_kwargs = _add_new_relic(
        layer_install(
            session=session,
            aws_region="us-east-1",
            nr_account_id=12345,
            enable_extension=True,
            enable_extension_function_logs=True,
            upgrade=True,
        ),
        config,
        "foobarbaz",
    )
    assert "NEW_RELIC_FOO" in update_kwargs["Environment"]["Variables"]
    assert update_kwargs["Layers"][0] != get_arn_prefix("us-east-1")


@mock_aws
def test_add_new_relic_apm_lambda_mode(aws_credentials, mock_function_config):
    session = boto3.Session(region_name="us-east-1")

    config = mock_function_config("python3.12")

    assert config["Configuration"]["Handler"] == "original_handler"

    update_kwargs = _add_new_relic(
        layer_install(
            session=session,
            aws_region="us-east-1",
            nr_account_id=12345,
            enable_extension=True,
            enable_extension_function_logs=True,
            apm=True,
        ),
        config,
        nr_license_key=None,
    )

    assert update_kwargs["FunctionName"] == config["Configuration"]["FunctionArn"]
    assert update_kwargs["Handler"] == "newrelic_lambda_wrapper.handler"
    assert (
        update_kwargs["Environment"]["Variables"]["NEW_RELIC_APM_LAMBDA_MODE"] == "True"
    )


def test_install_apm(aws_credentials, mock_function_config):
    mock_session = MagicMock()
    mock_session.region_name = "us-east-1"
    expected_tags_after_tagging = {
        "NR.Apm.Lambda.Mode": "true",
    }

    with patch(
        "newrelic_lambda_cli.layers._get_license_key_outputs"
    ) as mock_get_license_key_outputs:
        mock_client = mock_session.client.return_value

        mock_client.get_function.reset_mock(return_value=True)

        config = mock_function_config("python3.12")
        mock_client.get_function.return_value = config

        mock_get_license_key_outputs.return_value = ("license_arn", "12345", "policy")

        try:
            install(
                layer_install(
                    session=mock_session,
                    aws_region="us-east-1",
                    nr_account_id=12345,
                    apm=True,
                ),
                "APMLambda",
            )
        except UsageError as e:
            print(f"UsageError: {e}")

        mock_client.get_function.reset_mock()
        config = mock_function_config("python3.12")
        mock_client.get_function.return_value = config
        mock_client.list_tags.return_value = {"Tags": expected_tags_after_tagging}
        assert (
            install(
                layer_install(nr_account_id=12345, session=mock_session), "APMLambda"
            )
            is True
        )

        mock_client.assert_has_calls([call.get_function(FunctionName="APMLambda")])
        mock_client.assert_has_calls(
            [
                call.update_function_configuration(
                    FunctionName="arn:aws:lambda:us-east-1:5558675309:function:aws-python3-dev-hello",  # noqa
                    Environment={
                        "Variables": {
                            "EXISTING_ENV_VAR": "Hello World",
                            "NEW_RELIC_ACCOUNT_ID": "12345",
                            "NEW_RELIC_LAMBDA_HANDLER": "original_handler",
                            "NEW_RELIC_LAMBDA_EXTENSION_ENABLED": "false",
                            "NEW_RELIC_APM_LAMBDA_MODE": "True",
                        }
                    },
                    Layers=ANY,
                    Handler="newrelic_lambda_wrapper.handler",
                )
            ]
        )

        mock_client.assert_has_calls(
            [
                call.tag_resource(
                    Resource="arn:aws:lambda:us-east-1:5558675309:function:aws-python3-dev-hello",
                    Tags={
                        "NR.Apm.Lambda.Mode": "true",
                    },
                )
            ]
        )

        tags_from_list_tags = mock_client.list_tags(Resource="APMLambda")["Tags"]

        assert tags_from_list_tags == expected_tags_after_tagging


@mock_aws
def test_add_new_relic_dotnet(aws_credentials, mock_function_config):
    session = boto3.Session(region_name="us-east-1")

    test_runtimes = ["dotnet6", "dotnet8"]
    for test_runtime in test_runtimes:
        config = mock_function_config(test_runtime)

        assert config["Configuration"]["Handler"] == "original_handler"

        update_kwargs = _add_new_relic(
            layer_install(
                session=session,
                aws_region="us-east-1",
                nr_account_id=12345,
                enable_extension=True,
                enable_extension_function_logs=True,
            ),
            config,
            nr_license_key=None,
        )

        # .NET doesn't require specifying a handler by default
        assert "Handler" not in update_kwargs
        assert (
            "NEW_RELIC_LAMBDA_HANDLER" not in update_kwargs["Environment"]["Variables"]
        )

        assert update_kwargs["FunctionName"] == config["Configuration"]["FunctionArn"]
        assert (
            update_kwargs["Environment"]["Variables"]["NEW_RELIC_ACCOUNT_ID"] == "12345"
        )
        assert (
            update_kwargs["Environment"]["Variables"][
                "NEW_RELIC_LAMBDA_EXTENSION_ENABLED"
            ]
            == "true"
        )
        assert (
            update_kwargs["Environment"]["Variables"][
                "NEW_RELIC_EXTENSION_SEND_FUNCTION_LOGS"
            ]
            == "false"
        )

        # .NET specific environment variables
        assert (
            update_kwargs["Environment"]["Variables"]["CORECLR_ENABLE_PROFILING"] == "1"
        )
        assert (
            update_kwargs["Environment"]["Variables"]["CORECLR_PROFILER"]
            == "{36032161-FFC0-4B61-B559-F6C5D41BAE5A}"
        )
        assert (
            update_kwargs["Environment"]["Variables"]["CORECLR_NEWRELIC_HOME"]
            == "/opt/lib/newrelic-dotnet-agent"
        )
        assert (
            update_kwargs["Environment"]["Variables"]["CORECLR_PROFILER_PATH"]
            == "/opt/lib/newrelic-dotnet-agent/libNewRelicProfiler.so"
        )


@mock_aws
def test_add_new_relic_nodejs(aws_credentials, mock_function_config):
    """
    Tests adding New Relic layer and configuration to Node.js functions,
    including the standard and ESM wrapper handlers.
    """
    session = boto3.Session(region_name="us-east-1")
    nr_license_key = "test-license-key-nodejs"
    nr_account_id = 12345

    runtime = "nodejs20.x"

    # --- Scenario 1: Standard Node.js Handler (ESM disabled) ---
    print(f"\nTesting Node.js ({runtime}) Standard Handler...")
    original_std_handler = "original_handler"
    config_std = mock_function_config(runtime)

    install_opts_std = layer_install(
        session=session,
        aws_region="us-east-1",
        nr_account_id=nr_account_id,
        enable_extension=True,
        enable_extension_function_logs=True,
    )

    update_kwargs_std = _add_new_relic(
        install_opts_std,
        config_std,
        nr_license_key=nr_license_key,
    )

    assert update_kwargs_std is not False, "Expected update_kwargs, not False"
    assert (
        update_kwargs_std["FunctionName"] == config_std["Configuration"]["FunctionArn"]
    )
    assert update_kwargs_std["Handler"] == "newrelic-lambda-wrapper.handler"
    assert (
        update_kwargs_std["Environment"]["Variables"]["NEW_RELIC_LAMBDA_HANDLER"]
        == original_std_handler
    )
    assert update_kwargs_std["Environment"]["Variables"]["NEW_RELIC_ACCOUNT_ID"] == str(
        nr_account_id
    )
    assert (
        update_kwargs_std["Environment"]["Variables"]["NEW_RELIC_LICENSE_KEY"]
        == nr_license_key
    )
    assert (
        update_kwargs_std["Environment"]["Variables"][
            "NEW_RELIC_LAMBDA_EXTENSION_ENABLED"
        ]
        == "true"
    )
    assert (
        update_kwargs_std["Environment"]["Variables"][
            "NEW_RELIC_EXTENSION_SEND_FUNCTION_LOGS"
        ]
        == "false"
    )

    # --- Scenario 2: ESM Node.js Handler (ESM enabled) ---
    print(f"\nTesting Node.js ({runtime}) ESM Handler...")
    original_esm_handler = "original_handler"
    config_esm = mock_function_config(runtime)

    install_opts_esm = layer_install(
        session=session,
        aws_region="us-east-1",
        nr_account_id=nr_account_id,
        enable_extension=True,
        enable_extension_function_logs=True,
        esm=True,
    )

    update_kwargs_esm = _add_new_relic(
        install_opts_esm,
        config_esm,
        nr_license_key=nr_license_key,
    )

    assert update_kwargs_esm is not False, "Expected update_kwargs, not False"
    assert (
        update_kwargs_esm["FunctionName"] == config_esm["Configuration"]["FunctionArn"]
    )
    assert (
        update_kwargs_esm["Handler"]
        == "/opt/nodejs/node_modules/newrelic-esm-lambda-wrapper/index.handler"
    )
    assert (
        update_kwargs_esm["Environment"]["Variables"]["NEW_RELIC_LAMBDA_HANDLER"]
        == original_esm_handler
    )
    assert update_kwargs_esm["Environment"]["Variables"]["NEW_RELIC_ACCOUNT_ID"] == str(
        nr_account_id
    )
    assert (
        update_kwargs_esm["Environment"]["Variables"]["NEW_RELIC_LICENSE_KEY"]
        == nr_license_key
    )
    assert (
        update_kwargs_esm["Environment"]["Variables"][
            "NEW_RELIC_LAMBDA_EXTENSION_ENABLED"
        ]
        == "true"
    )
    assert (
        update_kwargs_esm["Environment"]["Variables"][
            "NEW_RELIC_EXTENSION_SEND_FUNCTION_LOGS"
        ]
        == "false"
    )


@mock_aws
def test_remove_new_relic(aws_credentials, mock_function_config):
    session = boto3.Session(region_name="us-east-1")

    config = mock_function_config("python3.12")
    config["Configuration"]["Handler"] = "newrelic_lambda_wrapper.handler"
    config["Configuration"]["Environment"]["Variables"][
        "NEW_RELIC_LAMBDA_HANDLER"
    ] = "original_handler"

    update_kwargs = _remove_new_relic(
        layer_uninstall(session=session, aws_region="us-east-1"), config
    )

    assert update_kwargs["FunctionName"] == config["Configuration"]["FunctionArn"]
    assert update_kwargs["Handler"] == "original_handler"
    assert not any(
        [k.startswith("NEW_RELIC") for k in update_kwargs["Environment"]["Variables"]]
    )

    config = mock_function_config("not.a.runtime")
    assert (
        _remove_new_relic(
            layer_uninstall(session=session, aws_region="us-east-1"), config
        )
        is True
    )

    config = mock_function_config("python3.12")
    config["Configuration"]["Handler"] = "what is this?"
    assert (
        _remove_new_relic(
            layer_uninstall(session=session, aws_region="us-east-1"), config
        )
        is False
    )

    config = mock_function_config("java11")
    config["Configuration"][
        "Handler"
    ] = "com.newrelic.java.HandlerWrapper::handleStreamsRequest"
    config["Configuration"]["Environment"]["Variables"][
        "NEW_RELIC_LAMBDA_HANDLER"
    ] = "original_handler"

    update_kwargs = _remove_new_relic(
        layer_uninstall(session=session, aws_region="us-east-1"), config
    )

    assert update_kwargs["FunctionName"] == config["Configuration"]["FunctionArn"]
    assert update_kwargs["Handler"] == "original_handler"
    assert not any(
        [k.startswith("NEW_RELIC") for k in update_kwargs["Environment"]["Variables"]]
    )


def test__attach_license_key_policy():
    mock_session = MagicMock()
    mock_client = mock_session.client.return_value

    assert (
        _attach_license_key_policy(
            mock_session,
            "arn:aws:iam::123456789:role/FooBar",
            "arn:aws:iam::123456789:policy/BarBaz",
        )
        is True
    )
    mock_client.attach_role_policy.assert_called_once_with(
        RoleName="FooBar", PolicyArn="arn:aws:iam::123456789:policy/BarBaz"
    )


def test__detach_license_key_policy():
    mock_session = MagicMock()
    mock_client = mock_session.client.return_value

    assert (
        _detach_license_key_policy(
            mock_session,
            "arn:aws:iam::123456789:role/FooBar",
            "arn:aws:iam::123456789:policy/BarBaz",
        )
        is True
    )
    mock_client.detach_role_policy.assert_called_once_with(
        RoleName="FooBar", PolicyArn="arn:aws:iam::123456789:policy/BarBaz"
    )


def test_install_failure(aws_credentials, mock_function_config):
    mock_session = MagicMock()
    mock_session.region_name = "us-east-1"
    mock_client = mock_session.client.return_value
    mock_client.get_function.reset_mock(return_value=True)
    with patch(
        "newrelic_lambda_cli.layers._get_license_key_outputs"
    ) as mock_get_license_key_outputs:
        mock_get_license_key_outputs.return_value = ("license_arn", "12345", "policy")
        config = mock_function_config("python3.12")
        mock_client.get_function.return_value = config
        with pytest.raises(UsageError):
            install(
                layer_install(nr_account_id=9876543, session=mock_session), "foobarbaz"
            )


def test_install(aws_credentials, mock_function_config):
    mock_session = MagicMock()
    mock_session.region_name = "us-east-1"

    with patch(
        "newrelic_lambda_cli.layers._get_license_key_outputs"
    ) as mock_get_license_key_outputs:
        mock_client = mock_session.client.return_value
        mock_client.get_function.reset_mock(return_value=True)
        mock_get_license_key_outputs.return_value = ("license_arn", "12345", "policy")
        config = mock_function_config("python3.12")
        mock_client.get_function.return_value = config
        with pytest.raises(UsageError):
            install(
                layer_install(nr_account_id=9876543, session=mock_session), "foobarbaz"
            )

        mock_client = mock_session.client.return_value
        mock_client.get_function.return_value = None
        assert (
            install(
                layer_install(nr_account_id=12345, session=mock_session), "foobarbaz"
            )
            is False
        )

        mock_client.get_function.reset_mock(return_value=True)
        config = mock_function_config("not.a.runtime")
        mock_client.get_function.return_value = config
        assert (
            install(
                layer_install(nr_account_id=12345, session=mock_session), "foobarbaz"
            )
            is False
        )

        mock_client.get_function.reset_mock(return_value=True)
        config = mock_function_config("python3.12")
        mock_client.get_function.return_value = config
        assert (
            install(
                layer_install(nr_account_id=12345, session=mock_session), "foobarbaz"
            )
            is True
        )

        mock_client.assert_has_calls([call.get_function(FunctionName="foobarbaz")])
        mock_client.assert_has_calls(
            [
                call.update_function_configuration(
                    FunctionName="arn:aws:lambda:us-east-1:5558675309:function:aws-python3-dev-hello",  # noqa
                    Environment={
                        "Variables": {
                            "EXISTING_ENV_VAR": "Hello World",
                            "NEW_RELIC_ACCOUNT_ID": "12345",
                            "NEW_RELIC_LAMBDA_HANDLER": "original_handler",
                            "NEW_RELIC_LAMBDA_EXTENSION_ENABLED": "false",
                        }
                    },
                    Layers=ANY,
                    Handler="newrelic_lambda_wrapper.handler",
                )
            ]
        )


def test_uninstall(aws_credentials, mock_function_config):
    mock_session = MagicMock()
    mock_session.region_name = "us-east-1"
    with patch(
        "newrelic_lambda_cli.layers._get_license_key_outputs"
    ) as mock_get_license_key_outputs:
        mock_get_license_key_outputs.return_value = ("license_arn", "12345", "policy")
        mock_client = mock_session.client.return_value
        mock_client.get_function.return_value = None
        assert uninstall(layer_uninstall(session=mock_session), "foobarbaz") is False

        mock_client.get_function.reset_mock(return_value=True)
        config = mock_function_config("not.a.runtime")
        mock_client.get_function.return_value = config
        assert uninstall(layer_uninstall(session=mock_session), "foobarbaz") is True

        mock_client.get_function.reset_mock(return_value=True)
        config = mock_function_config("python3.12")
        mock_client.get_function.return_value = config
        assert uninstall(layer_uninstall(session=mock_session), "foobarbaz") is False

        config["Configuration"]["Handler"] = "newrelic_lambda_wrapper.handler"
        config["Configuration"]["Environment"]["Variables"][
            "NEW_RELIC_LAMBDA_HANDLER"
        ] = "foobar.handler"
        config["Configuration"]["Role"] = "role_handler"
        config["Configuration"]["Layers"] = [{"Arn": get_arn_prefix("us-east-1")}]
        with patch(
            "newrelic_lambda_cli.layers._detach_license_key_policy"
        ) as mock_detach_license_key_policy:
            mock_detach_license_key_policy.return_value = True

            assert uninstall(layer_uninstall(session=mock_session), "foobarbaz") is True
            mock_detach_license_key_policy.assert_called_once_with(
                mock_session, "role_handler", "policy"
            )
            mock_client.assert_has_calls([call.get_function(FunctionName="foobarbaz")])
            mock_client.assert_has_calls(
                [
                    call.update_function_configuration(
                        FunctionName="arn:aws:lambda:us-east-1:5558675309:function:aws-python3-dev-hello",  # noqa
                        Handler="foobar.handler",
                        Environment={"Variables": {"EXISTING_ENV_VAR": "Hello World"}},
                        Layers=[],
                    )
                ]
            )


@mock_aws
def test_install_success_message_new_layer(aws_credentials, mock_function_config):
    """Test that the correct success message is shown when installing a layer on a function with no existing layers"""

    mock_session = MagicMock()
    mock_session.region_name = "us-east-1"

    with patch(
        "newrelic_lambda_cli.layers._get_license_key_outputs"
    ) as mock_get_license_key_outputs, patch(
        "newrelic_lambda_cli.layers.success"
    ) as mock_success:

        mock_get_license_key_outputs.return_value = ("license_arn", "12345", "policy")
        mock_client = mock_session.client.return_value

        config = mock_function_config("python3.12")
        config["Configuration"]["Layers"] = []
        mock_client.get_function.return_value = config

        new_layer_arn = (
            "arn:aws:lambda:us-east-1:451483290750:layer:NewRelicPython39:35"
        )

        with patch("newrelic_lambda_cli.layers._add_new_relic") as mock_add_new_relic:
            mock_add_new_relic.return_value = {
                "FunctionName": "test-function-name",
                "Layers": [new_layer_arn],
            }

            function_arn = "test-function-arn"
            result = install(
                layer_install(nr_account_id=12345, session=mock_session), function_arn
            )

            assert result is True

            mock_success.assert_called_once_with(
                "Successfully installed Layer ARN %s for the function: %s"
                % (new_layer_arn, function_arn)
            )


@mock_aws
def test_extension_logs_flags(aws_credentials, mock_function_config):
    """Test that --send-extension-logs and --disable-extension-logs flags work correctly"""
    session = boto3.Session(region_name="us-east-1")
    nr_account_id = 12345

    # Test 1: Fresh install with default settings - logs should be disabled by default
    config = mock_function_config("python3.12")
    update_kwargs = _add_new_relic(
        layer_install(
            session=session,
            aws_region="us-east-1",
            nr_account_id=nr_account_id,
            enable_extension=True,
        ),
        config,
        nr_license_key=None,
    )

    assert (
        update_kwargs["Environment"]["Variables"][
            "NEW_RELIC_EXTENSION_SEND_EXTENSION_LOGS"
        ]
        == "false"
    )

    # Test 2: Fresh install with --send-extension-logs
    config = mock_function_config("python3.12")
    update_kwargs = _add_new_relic(
        layer_install(
            session=session,
            aws_region="us-east-1",
            nr_account_id=nr_account_id,
            enable_extension=True,
            send_extension_logs=True,
        ),
        config,
        nr_license_key=None,
    )

    assert (
        update_kwargs["Environment"]["Variables"][
            "NEW_RELIC_EXTENSION_SEND_EXTENSION_LOGS"
        ]
        == "false"
    )

    # Test 3: Upgrade with --send-extension-logs - should set to true
    config = mock_function_config("python3.12")
    config["Configuration"]["Environment"]["Variables"][
        "NEW_RELIC_EXTENSION_SEND_EXTENSION_LOGS"
    ] = "false"

    update_kwargs = _add_new_relic(
        layer_install(
            session=session,
            aws_region="us-east-1",
            nr_account_id=nr_account_id,
            enable_extension=True,
            send_extension_logs=True,
            upgrade=True,
        ),
        config,
        nr_license_key=None,
    )

    assert (
        update_kwargs["Environment"]["Variables"][
            "NEW_RELIC_EXTENSION_SEND_EXTENSION_LOGS"
        ]
        == "true"
    )

    # Test 4: Upgrade with --disable-extension-logs - should set to false
    config = mock_function_config("python3.12")
    config["Configuration"]["Environment"]["Variables"][
        "NEW_RELIC_EXTENSION_SEND_EXTENSION_LOGS"
    ] = "true"

    update_kwargs = _add_new_relic(
        layer_install(
            session=session,
            aws_region="us-east-1",
            nr_account_id=nr_account_id,
            enable_extension=True,
            disable_extension_logs=True,
            upgrade=True,
        ),
        config,
        nr_license_key=None,
    )

    assert (
        update_kwargs["Environment"]["Variables"][
            "NEW_RELIC_EXTENSION_SEND_EXTENSION_LOGS"
        ]
        == "false"
    )

    # Test 5: Upgrade without flags - should preserve existing value
    config = mock_function_config("python3.12")
    config["Configuration"]["Environment"]["Variables"][
        "NEW_RELIC_EXTENSION_SEND_EXTENSION_LOGS"
    ] = "true"

    update_kwargs = _add_new_relic(
        layer_install(
            session=session,
            aws_region="us-east-1",
            nr_account_id=nr_account_id,
            enable_extension=True,
            upgrade=True,
        ),
        config,
        nr_license_key=None,
    )

    assert (
        update_kwargs["Environment"]["Variables"][
            "NEW_RELIC_EXTENSION_SEND_EXTENSION_LOGS"
        ]
        == "true"
    )


@mock_aws
def test_function_logs_flags(aws_credentials, mock_function_config):
    """Test that --send-function-logs and --disable-function-logs flags work correctly"""
    session = boto3.Session(region_name="us-east-1")
    nr_account_id = 12345

    # Test 1: Fresh install with default settings - logs should be disabled by default
    config = mock_function_config("python3.12")
    update_kwargs = _add_new_relic(
        layer_install(
            session=session,
            aws_region="us-east-1",
            nr_account_id=nr_account_id,
            enable_extension=True,
        ),
        config,
        nr_license_key=None,
    )

    assert (
        update_kwargs["Environment"]["Variables"][
            "NEW_RELIC_EXTENSION_SEND_FUNCTION_LOGS"
        ]
        == "false"
    )

    # Test 2: Fresh install with --send-function-logs - should still be false
    config = mock_function_config("python3.12")
    update_kwargs = _add_new_relic(
        layer_install(
            session=session,
            aws_region="us-east-1",
            nr_account_id=nr_account_id,
            enable_extension=True,
            send_function_logs=True,
        ),
        config,
        nr_license_key=None,
    )

    assert (
        update_kwargs["Environment"]["Variables"][
            "NEW_RELIC_EXTENSION_SEND_FUNCTION_LOGS"
        ]
        == "false"
    )

    # Test 3: Upgrade with --send-function-logs - should set to true
    config = mock_function_config("python3.12")
    config["Configuration"]["Environment"]["Variables"][
        "NEW_RELIC_EXTENSION_SEND_FUNCTION_LOGS"
    ] = "false"

    update_kwargs = _add_new_relic(
        layer_install(
            session=session,
            aws_region="us-east-1",
            nr_account_id=nr_account_id,
            enable_extension=True,
            send_function_logs=True,
            upgrade=True,
        ),
        config,
        nr_license_key=None,
    )

    assert (
        update_kwargs["Environment"]["Variables"][
            "NEW_RELIC_EXTENSION_SEND_FUNCTION_LOGS"
        ]
        == "true"
    )

    # Test 4: Upgrade with --disable-function-logs - should set to false
    config = mock_function_config("python3.12")
    config["Configuration"]["Environment"]["Variables"][
        "NEW_RELIC_EXTENSION_SEND_FUNCTION_LOGS"
    ] = "true"

    update_kwargs = _add_new_relic(
        layer_install(
            session=session,
            aws_region="us-east-1",
            nr_account_id=nr_account_id,
            enable_extension=True,
            disable_function_logs=True,
            upgrade=True,
        ),
        config,
        nr_license_key=None,
    )

    assert (
        update_kwargs["Environment"]["Variables"][
            "NEW_RELIC_EXTENSION_SEND_FUNCTION_LOGS"
        ]
        == "false"
    )

    # Test 5: Upgrade without flags - should preserve existing value
    config = mock_function_config("python3.12")
    config["Configuration"]["Environment"]["Variables"][
        "NEW_RELIC_EXTENSION_SEND_FUNCTION_LOGS"
    ] = "true"

    update_kwargs = _add_new_relic(
        layer_install(
            session=session,
            aws_region="us-east-1",
            nr_account_id=nr_account_id,
            enable_extension=True,
            upgrade=True,
        ),
        config,
        nr_license_key=None,
    )

    assert (
        update_kwargs["Environment"]["Variables"][
            "NEW_RELIC_EXTENSION_SEND_FUNCTION_LOGS"
        ]
        == "true"
    )


@mock_aws
def test_independent_log_settings(aws_credentials, mock_function_config):
    """Test that function logs and extension logs are independent settings"""
    session = boto3.Session(region_name="us-east-1")
    nr_account_id = 12345

    # Test: Upgrade with one flag should not affect the other setting
    config = mock_function_config("python3.12")
    config["Configuration"]["Environment"]["Variables"][
        "NEW_RELIC_EXTENSION_SEND_FUNCTION_LOGS"
    ] = "true"
    config["Configuration"]["Environment"]["Variables"][
        "NEW_RELIC_EXTENSION_SEND_EXTENSION_LOGS"
    ] = "true"

    # Set only function logs to false
    update_kwargs = _add_new_relic(
        layer_install(
            session=session,
            aws_region="us-east-1",
            nr_account_id=nr_account_id,
            enable_extension=True,
            disable_function_logs=True,
            upgrade=True,
        ),
        config,
        nr_license_key=None,
    )

    # Function logs should be set to false, extension logs should be preserved
    assert (
        update_kwargs["Environment"]["Variables"][
            "NEW_RELIC_EXTENSION_SEND_FUNCTION_LOGS"
        ]
        == "false"
    )
    assert (
        update_kwargs["Environment"]["Variables"][
            "NEW_RELIC_EXTENSION_SEND_EXTENSION_LOGS"
        ]
        == "true"
    )
