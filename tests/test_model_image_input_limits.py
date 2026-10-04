from pi_mono.ai.models import _apply_image_input_metadata
from pi_mono.ai.types import Model


def test_image_input_metadata_applies_default_resize_and_provider_limits() -> None:
    model: Model = {"provider": "anthropic", "input": ["text", "image"], "contextWindow": 200000}

    _apply_image_input_metadata(model)

    assert model["inputLimits"] == {
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
    }
