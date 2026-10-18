from clients.mini_sre import mini


def test_mini_sre_includes_opensre_diagnosis(monkeypatch):
    monkeypatch.setenv("OPENSRE_DIAGNOSIS_CONTEXT", "The service selector does not match the pods.")
    monkeypatch.setattr(mini, "build_task_text", lambda app_info: "task")

    prompt = mini.instance_text({})

    assert "Upstream OpenSRE diagnosis" in prompt
    assert "service selector does not match" in prompt
    assert "Validate this diagnosis" in prompt
