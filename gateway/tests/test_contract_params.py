from powermcp_gateway.contracts.params import schema_is_unusable, validate_args

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


def test_malformed_schema_values_do_not_raise():
    """★ 畸形 schema 不得让校验器抛异常 —— 异常会逃出 call_tool 变成 HTTP 500。

    原实现 `tuple(t)`（对 `type=5`）/ `tuple(x["type"] ...)`（对 `anyOf=5`）直接崩。
    修正后安全退化为 `()`，与「非 dict 的 prop 跳过」的 fail-open 立场一致。
    """
    for prop in ({"type": 5}, {"anyOf": 5}, {"type": ["str", 5]},
                 {"type": None}, {"anyOf": None}):
        out = validate_args({"properties": {"x": prop}}, {"x": 1})
        assert isinstance(out, tuple), f"prop={prop} 应返回元组而非抛异常"


def test_malformed_type_list_keeps_only_strings():
    """list 型 `type` 里的非 str 元素被丢弃、只留 str（取舍见 `_accepted_types` docstring）。"""
    schema = {"properties": {"x": {"type": ["string", 5]}}}
    assert validate_args(schema, {"x": "ok"}) == ()
    assert [v.kind for v in validate_args(schema, {"x": 1})] == ["wrong_type"]


def test_violations_are_sorted():
    """违规按参数名排序。

    注：名字原为 `..._and_deduped` —— 但「去重」不可达（输入 dict 的键天然唯一，
    unknown_arg 分支也用了 `set()`），故改名如实描述被测行为（只改名字，不改行为）。
    """
    v = validate_args(SCHEMA, {"network_name": "n", "zzz": 1, "aaa": 2})
    assert [x.arg for x in v] == ["aaa", "zzz"]


# ── C-1：把"无法判定的 schema"标出来（否则它被静默 fail-open）──────────────


def test_schema_is_unusable_flags_malformed_shapes():
    """良构/缺省 → False；畸形 → True。**本函数不改变 `validate_args` 的行为**，
    只是为 `call_tool` 提供一个附加判定，让它能对"无法判定"补发 structural unknown
    —— 否则同类畸形会出现"一个报告（走异常路径）、一个沉默（走安全返回路径）"。
    """
    # 良构
    assert schema_is_unusable(SCHEMA) is False
    assert schema_is_unusable({}) is False                                  # 无 properties → 无从判定
    assert schema_is_unusable({"properties": {}}) is False
    assert schema_is_unusable({"properties": {"x": {"type": ["string", "null"]}}}) is False
    assert schema_is_unusable({"properties": {"x": {"anyOf": [{"type": "string"}]}}}) is False

    # 畸形
    for bad in (
        {"properties": 5},
        {"properties": {"x": 5}},
        {"properties": {"x": {"type": 5}}},
        {"properties": {"x": {"type": ["string", 5]}}},
        {"properties": {"x": {"anyOf": 5}}},
        {"properties": {"x": {"anyOf": [{"type": 5}]}}},
        {"properties": {"x": {"anyOf": ["nope"]}}},
    ):
        assert schema_is_unusable(bad) is True, f"未检出畸形 schema：{bad}"

    # 对任何畸形**不抛异常**（它是"隔离坏输入"的那一层）
    for weird in (None, 5, "x", []):
        assert schema_is_unusable(weird) is True
