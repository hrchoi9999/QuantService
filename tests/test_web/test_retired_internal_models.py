from service_platform.web.internal_models_api import InternalModelsApi


def test_internal_model_validation_excludes_retired_models() -> None:
    api = InternalModelsApi.__new__(InternalModelsApi)
    current_payload = {
        "summary": {
            "model_count": 3,
            "action_required_count": 2,
            "by_review_state": {"OK": 1, "ACTION_REQUIRED": 2},
        },
        "models": [
            {"model_code": "S2", "review_state": "OK", "validation_score": {}},
            {
                "model_code": "S2_PIT_V01",
                "review_state": "ACTION_REQUIRED",
                "validation_score": {},
            },
            {
                "model_code": "I-STOCK-STRONG-RSI-V01",
                "review_state": "ACTION_REQUIRED",
                "validation_score": {},
            },
        ],
    }

    view = api._build_validation_view(current_payload, {"history": []})

    assert [row["model_code"] for row in view["models"]] == ["S2"]
    assert view["summary"]["model_count"] == 1
    assert view["summary"]["action_required_count"] == 0
    assert view["summary"]["by_review_state"] == {"OK": 1}
