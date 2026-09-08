"""Offline checks for GraphQL component parameter and current-unit resolution."""

from __future__ import annotations

import sys
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

from mylib.component_metadata import resolve_current_parameter_metadata  # noqa: E402


def response(*, unit=None, name="3 Phase Branch Current", description=""):
    return {
        "data": {
            "model": {
                "rid": "model/CloudPSS/_newFaultResistor_3p",
                "name": "Fault resistor",
                "revision": {
                    "parameters": [
                        {
                            "name": "Signals",
                            "items": [
                                {
                                    "key": "I",
                                    "name": name,
                                    "description": description,
                                    "unit": unit,
                                }
                            ],
                        }
                    ]
                },
            }
        }
    }


def resolve(payload):
    return resolve_current_parameter_metadata(
        "model/CloudPSS/_newFaultResistor_3p",
        request=lambda _query, _variables, **_kwargs: payload,
    )


def assert_fails(payload, text: str) -> None:
    try:
        resolve(payload)
    except Exception as exc:
        assert text in str(exc)
    else:
        raise AssertionError(f"Expected failure containing {text!r}")


def main() -> None:
    explicit = resolve(response(unit="kA", name="Current [A]"))
    assert explicit["raw_unit"] == "kA"
    assert explicit["unit_source"] == "parameter.unit"
    assert explicit["unit_scale_to_ka"] == 1.0

    fallback = resolve(response(unit=None, name="3 Phase Branch Current [kA]"))
    assert fallback["raw_unit"] == "kA"
    assert fallback["unit_source"] == "parameter.name"

    amperes = resolve(response(unit="A"))
    assert amperes["unit_scale_to_ka"] == 0.001

    milliamperes = resolve(response(unit="mA"))
    assert milliamperes["unit_scale_to_ka"] == 1e-6

    megaamperes = resolve(response(unit="MA"))
    assert megaamperes["unit_scale_to_ka"] == 1e3

    assert_fails(response(unit=None), "Current unit is missing")
    assert_fails(response(unit="ampere"), "Unsupported current unit")
    assert_fails(response(unit=None, name="Current [A] [kA]"), "Conflicting")
    assert_fails({"errors": [{"message": "denied"}]}, "could not read")
    assert_fails({"data": {"model": None}}, "not found or is not accessible")

    print("component metadata checks: OK")


if __name__ == "__main__":
    main()
