from pi_mono.ai.providers.azure_openai_responses import _build_params


def test_build_params_merges_model_and_request_sampling_params():
    model = {
        "id": "gpt-5",
        "provider": "azure-openai-responses",
        "samplingParams": {"temperature": 0.2, "top_p": 0.8},
    }
    context = {"messages": [{"role": "user", "content": "hi"}]}

    params = _build_params(
        model,
        context,
        {"samplingParams": {"temperature": 0.7}},
        "gpt-5-deployment",
    )

    assert params["temperature"] == 0.7
    assert params["top_p"] == 0.8
