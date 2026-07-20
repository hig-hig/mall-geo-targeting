from mall_geo_targeting.commercial_processing import classify_commercial


def test_commercial_classification_is_single_and_priority_ordered() -> None:
    assert classify_commercial({"shop": "supermarket"}) == "supermarket"
    assert classify_commercial({"shop": "convenience"}) == "convenience_store"
    assert classify_commercial({"shop": "bakery"}) == "retail"
    assert classify_commercial({"shop": "hairdresser"}) == "service"
    assert classify_commercial({"amenity": "restaurant", "shop": "yes"}) == "restaurant"
    assert classify_commercial({"leisure": "amusement_arcade"}) == "entertainment"
    assert classify_commercial({"office": "company"}) == "office"


def test_noncommercial_and_vacant_features_are_not_classified() -> None:
    assert classify_commercial({"amenity": "parking"}) is None
    assert classify_commercial({"highway": "bus_stop"}) is None
    assert classify_commercial({"shop": "vacant"}) is None
