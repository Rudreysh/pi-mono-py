from pi_mono.ai.types import Model


def test_model_supports_image_input_limit_metadata() -> None:
    model: Model = {
        "id": "vision",
        "input": ["text", "image"],
        "inputLimits": {
            "maxRequestBytes": 32 * 1024 * 1024,
            "images": {
                "maxPerRequest": 100,
                "resize": {
                    "maxWidth": 2000,
                    "maxHeight": 2000,
                    "maxBytes": int(4.5 * 1024 * 1024),
                    "jpegQuality": 80,
                },
            },
        },
    }

    assert model["inputLimits"]["images"]["resize"]["maxWidth"] == 2000
