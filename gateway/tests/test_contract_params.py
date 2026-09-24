from powermcp_gateway.contracts.params import validate_args

SCHEMA = {
    "type": "object",
    "properties": {
        "network_name": {"type": "string"},
        "solver_name": {"type": "string"},
        "linear": {"type": "boolean"},
        "max_iter": {"type": "integer"},
    },
    "required": ["network_name"],
}


def test_valid_args_produce_no_violations():
    assert validate_args(SCHEMA, {"network_name": "n", "linear": True}) == ()


def test_unknown_arg_is_flagged():
    """★ 这就是 linearized 那类缺陷 —— 传了声明里没有的参数，会被引擎静默忽略。"""
    v = validate_args(SCHEMA, {"network_name": "n", "linearized": True})
    assert len(v) == 1
    assert v[0].kind == "unknown_arg"
    assert v[0].arg == "linearized"


def test_missing_required_is_flagged():
    v = validate_args(SCHEMA, {})
    assert [x.kind for x in v] == ["missing_required"]
    assert v[0].arg == "network_name"


def test_wrong_type_is_flagged():
    v = validate_args(SCHEMA, {"network_name": 123})
    assert v[0].kind == "wrong_type"
    assert v[0].arg == "network_name"


def test_bool_is_not_accepted_as_integer():
    """Python 里 bool 是 int 的子类 —— 必须显式排除，否则 True 会被当成合法整数。"""
    v = validate_args(SCHEMA, {"network_name": "n", "max_iter": True})
    assert [x.kind for x in v] == ["wrong_type"]


def test_schema_without_properties_accepts_anything():
    assert validate_args({}, {"anything": 1}) == ()
    assert validate_args({"type": "object"}, {"anything": 1}) == ()


def test_anyof_with_null_accepts_none():
    """真实 schema 形态：solver_options 是 anyOf:[object, null]。"""
    schema = {"properties": {"opts": {"anyOf": [{"type": "object"}, {"type": "null"}]}}}
    assert validate_args(schema, {"opts": None}) == ()


def test_violations_are_sorted_and_deduped():
    v = validate_args(SCHEMA, {"network_name": "n", "zzz": 1, "aaa": 2})
    assert [x.arg for x in v] == ["aaa", "zzz"]
