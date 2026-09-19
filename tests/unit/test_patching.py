import pytest

from agentops.mcp_server.patching import PatchError, apply_patch_to_text, parse_unified_diff

ORIGINAL = "def add(a, b):\n    return a - b\n\n\ndef sub(a, b):\n    return a - b\n"

DIFF = """--- a/math_ops.py
+++ b/math_ops.py
@@ -1,3 +1,3 @@
 def add(a, b):
-    return a - b
+    return a + b

"""


def test_parse_extracts_target_path():
    parsed = parse_unified_diff(DIFF)
    assert parsed.target_path == "math_ops.py"
    assert len(parsed.hunks) == 1


def test_apply_patch_fixes_the_bug():
    parsed = parse_unified_diff(DIFF)
    patched = apply_patch_to_text(ORIGINAL, parsed)
    assert "def add(a, b):\n    return a + b" in patched
    assert "def sub(a, b):\n    return a - b" in patched  # unrelated function untouched


def test_apply_patch_rejects_mismatched_context():
    parsed = parse_unified_diff(DIFF)
    wrong_original = "def add(a, b):\n    return 0\n\n\ndef sub(a, b):\n    return a - b\n"
    with pytest.raises(PatchError):
        apply_patch_to_text(wrong_original, parsed)


def test_parse_rejects_diff_without_hunks():
    with pytest.raises(PatchError):
        parse_unified_diff("--- a/x.py\n+++ b/x.py\n")


def test_parse_rejects_diff_without_target():
    with pytest.raises(PatchError):
        parse_unified_diff("@@ -1,1 +1,1 @@\n-old\n+new\n")
