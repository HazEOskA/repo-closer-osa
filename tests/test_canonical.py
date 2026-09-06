from repo_closer.canonical import canonical_json, sha256_hex


def test_canonical_hash_is_order_independent_for_dicts():
    a = {"b": 2, "a": {"y": 2, "x": 1}}
    b = {"a": {"x": 1, "y": 2}, "b": 2}
    assert canonical_json(a) == canonical_json(b)
    assert sha256_hex(a) == sha256_hex(b)
