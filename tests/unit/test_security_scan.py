from agentops.agent.security_scan import scan_diff_for_issues


def _diff(added_line: str) -> str:
    return f"--- a/src/module.py\n+++ b/src/module.py\n@@ -1,1 +1,2 @@\n def f():\n+{added_line}\n"


def test_detects_eval():
    findings = scan_diff_for_issues(_diff("    eval(user_input)"))
    assert any("eval" in f for f in findings)


def test_detects_os_system():
    findings = scan_diff_for_issues(_diff("    os.system(cmd)"))
    assert any("os.system" in f for f in findings)


def test_detects_shell_true():
    findings = scan_diff_for_issues(_diff("    subprocess.run(cmd, shell=True)"))
    assert any("shell=True" in f for f in findings)


def test_detects_hardcoded_secret():
    findings = scan_diff_for_issues(_diff('    API_KEY = "sk-abcdefghijklmnopqrstuvwx"'))
    assert any("secret" in f.lower() for f in findings)


def test_ignores_removed_lines():
    diff = "--- a/src/module.py\n+++ b/src/module.py\n@@ -1,2 +1,1 @@\n def f():\n-    eval(x)\n"
    assert scan_diff_for_issues(diff) == []


def test_clean_diff_has_no_findings():
    findings = scan_diff_for_issues(_diff("    return a + b"))
    assert findings == []


def test_does_not_duplicate_the_same_finding():
    diff = _diff("    eval(a)") + "+    eval(b)\n"
    findings = scan_diff_for_issues(diff)
    assert findings.count(next(f for f in findings if "eval" in f)) == 1
