from research.strategy_adapter_safety import validate_adapter_source


def test_pandas_signal_adapter_is_allowed():
    source = "import pandas as pd\n\ndef strategy(frame):\n    return pd.Series(0, index=frame.index)\n"
    result = validate_adapter_source(source)
    assert result.safe is True
    assert result.errors == ()


def test_broker_network_and_process_imports_are_blocked():
    for module in ("alpaca", "requests", "socket", "subprocess"):
        result = validate_adapter_source(f"import {module}\n")
        assert result.safe is False
        assert any(module in error for error in result.errors)


def test_from_import_is_checked_by_root_module():
    result = validate_adapter_source("from urllib.request import urlopen\n")
    assert result.safe is False
    assert "urllib" in result.errors[0]


def test_dynamic_execution_is_blocked():
    for expression in ("eval('1+1')", "exec('x=1')", "__import__('os')"):
        assert validate_adapter_source(expression).safe is False


def test_order_authority_names_are_blocked_even_without_broker_import():
    source = "def strategy(client):\n    return client.submit_order(symbol='SPY')\n"
    result = validate_adapter_source(source)
    assert result.safe is False
    assert "forbidden_call.submit_order" in result.errors


def test_syntax_error_fails_closed():
    result = validate_adapter_source("def strategy(:\n")
    assert result.safe is False
    assert result.errors[0].startswith("syntax_error.")
