"""Schema introspection. No network: the fixture mirrors the real response."""
from app.federato.schema import SchemaIndex

RAW = {
    "Policy": {"type": "object", "fields": {
        "id": {"type": "number"},
        "premium": {"type": "number"},
        "status": {"type": "string"},
        "dates": {"type": "object", "fields": {"effective": {"type": "string"}}},
        "insured": {"type": "reference", "resource": "Insured", "cardinality": "one"},
        "exposure_units": {"type": "reference", "resource": "ExposureUnit",
                           "cardinality": "many"},
    }},
    "Insured": {"type": "object", "fields": {
        "id": {"type": "number"},
        "name": {"type": "string"},
        "hq": {"type": "reference", "resource": "Location", "cardinality": "one"},
    }},
    "ExposureUnit": {"type": "object", "fields": {
        "id": {"type": "number"},
        "location": {"type": "reference", "resource": "Location", "cardinality": "one"},
    }},
    "Location": {"type": "object", "fields": {
        "id": {"type": "number"},
        "state": {"type": "string"},
        "hazard_tags": {"type": "array", "itemSchema": {"type": "string"}},
        "buildings": {"type": "reference", "resource": "Building", "cardinality": "many"},
    }},
    "Building": {"type": "object", "fields": {
        "id": {"type": "number"},
        "tiv": {"type": "number"},
        "construction_type": {"type": "string"},
    }},
    "Submission": {"type": "object", "fields": {
        "id": {"type": "number"},
        "locations": {"type": "array", "itemSchema": {
            "type": "object", "fields": {"state": {"type": "string"}}}},
    }},
}


def idx() -> SchemaIndex:
    return SchemaIndex(RAW)


def test_flattens_nested_objects_to_dot_paths():
    assert idx().field("Policy", "dates.effective").type == "string"


def test_reference_fields_carry_target_and_cardinality():
    f = idx().field("Policy", "exposure_units")
    assert f.type == "reference"
    assert f.resource == "ExposureUnit"
    assert f.cardinality == "many"


def test_rejects_dot_path_through_an_array_with_an_elemmatch_hint():
    """The documented pitfall: the API accepts this and silently matches nothing."""
    ok, hint = idx().validate_path("Submission", "locations.state")
    assert ok is False
    assert "$elemMatch" in hint


def test_accepts_a_plain_scalar_path():
    assert idx().validate_path("Policy", "premium") == (True, None)


def test_unknown_field_suggests_a_near_match():
    ok, hint = idx().validate_path("Policy", "premiums")
    assert ok is False
    assert "premium" in hint


def test_finds_every_minimal_route_to_building_not_just_the_first():
    """Both routes reach different buildings; dropping either loses footprint."""
    routes = idx().paths_between("Policy", "Building")
    assert ["insured", "hq", "buildings"] in routes
    assert ["exposure_units", "location", "buildings"] in routes


def test_merges_routes_into_a_single_expand_stage():
    merged = idx().merge_expands(idx().paths_between("Policy", "Building"))
    assert merged["insured"]["hq"]["buildings"] is True
    assert merged["exposure_units"]["location"]["buildings"] is True


def test_unreachable_target_returns_no_route():
    assert idx().paths_between("Building", "Policy") == []
