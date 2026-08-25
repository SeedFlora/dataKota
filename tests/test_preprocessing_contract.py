from __future__ import annotations

from copy import deepcopy

import pytest

from crm.preprocessing_contract import (
    PreprocessingContractError,
    preprocessing_sha256,
    validate_preprocessing_contract,
)
from tests.preprocessing_examples import image_preprocessing, text_preprocessing


def test_complete_hf_style_image_contract_is_accepted() -> None:
    contract = image_preprocessing()
    contract["implementation"] = {
        "framework": "huggingface_transformers",
        "library": "transformers",
        "library_version": "4.55.0",
        "processor_class": "transformers.AutoImageProcessor",
        "configuration_source": "repository_assets",
        "processor_repository": "org/image-encoder",
        "processor_revision": "a" * 40,
        "assets": [{"path": "preprocessor_config.json", "sha256": "b" * 64}],
    }
    validated = validate_preprocessing_contract(
        contract,
        modality="image",
        pooling="cls_token",
        prefix=None,
        max_length=None,
        output_dtype="float32",
    )
    assert validated is contract
    assert len(preprocessing_sha256(contract)) == 64


def test_complete_timm_explicit_image_contract_is_accepted() -> None:
    contract = image_preprocessing()
    contract["implementation"].update(
        {
            "framework": "timm",
            "library": "timm",
            "library_version": "1.0.19",
            "processor_class": "timm.data.create_transform",
        }
    )
    validate_preprocessing_contract(
        contract,
        modality="image",
        pooling="cls_token",
        prefix=None,
        max_length=None,
        output_dtype="float32",
    )


def test_image_contract_rejects_implicit_orientation_or_normalization() -> None:
    for path in (("decode", "exif_orientation"), ("numeric", "mean")):
        contract = deepcopy(image_preprocessing())
        del contract[path[0]][path[1]]
        with pytest.raises(PreprocessingContractError, match="keys are not exact"):
            validate_preprocessing_contract(contract, modality="image")


def test_text_contract_binds_cleaning_tokenizer_and_pooling() -> None:
    contract = text_preprocessing()
    validate_preprocessing_contract(
        contract,
        modality="text",
        pooling="e5_avg",
        prefix="query: ",
        max_length=16,
        output_dtype="float32",
    )

    changed = deepcopy(contract)
    changed["tokenization"]["padding"] = "implicit"
    with pytest.raises(PreprocessingContractError, match="padding"):
        validate_preprocessing_contract(changed, modality="text")


def test_top_level_text_runtime_fields_must_match_nested_contract() -> None:
    contract = text_preprocessing()
    with pytest.raises(PreprocessingContractError, match="prefix differs"):
        validate_preprocessing_contract(
            contract,
            modality="text",
            pooling="e5_avg",
            prefix="passage: ",
            max_length=16,
            output_dtype="float32",
        )


def test_unknown_preprocessing_field_is_rejected() -> None:
    contract = image_preprocessing()
    contract["hidden_default"] = True
    with pytest.raises(PreprocessingContractError, match="unexpected"):
        validate_preprocessing_contract(contract, modality="image")
