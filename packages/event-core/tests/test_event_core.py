"""Tests for the Kafka-independent parts of construction_enterprise_os_event_core.

The publisher / subscriber require a Kafka broker (aiokafka) and are not covered here.
"""

import json
import sys
from datetime import datetime
from uuid import UUID

import pytest

from construction_enterprise_os_event_core import (
    TOPIC_MAP,
    CloudEvent,
    EventTypes,
    create_document_event,
    create_iot_event,
    create_user_event,
    create_workflow_event,
)


def _event_type_values() -> list[str]:
    return [v for k, v in vars(EventTypes).items() if k.isupper()]


def test_package_import_does_not_require_aiokafka():
    # publisher / subscriber are imported lazily via get_publisher / get_subscriber
    assert "construction_enterprise_os_event_core.publisher" not in sys.modules
    assert "construction_enterprise_os_event_core.subscriber" not in sys.modules


def test_cloud_event_defaults():
    event = CloudEvent(type=EventTypes.USER_CREATED, source="/services/auth")
    UUID(event.id)  # raises if not a UUID
    assert datetime.fromisoformat(event.time).tzinfo is not None
    assert event.datacontenttype == "application/json"
    assert event.subject is None
    assert event.data == {}


def test_cloud_event_ids_are_unique():
    a = CloudEvent(type="t", source="s")
    b = CloudEvent(type="t", source="s")
    assert a.id != b.id


def test_cloud_event_json_round_trip_keeps_non_ascii():
    event = CloudEvent(
        type=EventTypes.DOCUMENT_UPLOADED,
        source="/services/document",
        subject="doc-1",
        data={"title": "施工計画書"},
    )
    raw = event.to_json()
    assert "施工計画書" in raw  # ensure_ascii=False
    assert CloudEvent.from_json(raw) == event
    assert set(json.loads(raw)) == {
        "type", "source", "id", "time", "subject", "datacontenttype", "data",
    }


@pytest.mark.parametrize(
    ("factory", "args", "source", "subject", "data"),
    [
        (
            create_user_event,
            (EventTypes.USER_LOGIN, "u1", "o1", {"ip": "x"}),
            "/services/auth",
            "u1",
            {"user_id": "u1", "organization_id": "o1", "ip": "x"},
        ),
        (
            create_document_event,
            (EventTypes.DOCUMENT_APPROVED, "d1", "u1", {}),
            "/services/document",
            "d1",
            {"document_id": "d1", "user_id": "u1"},
        ),
        (
            create_iot_event,
            (EventTypes.IOT_ALERT, "dev1", {"level": "high"}),
            "/services/iot",
            "dev1",
            {"device_id": "dev1", "level": "high"},
        ),
        (
            create_workflow_event,
            (EventTypes.WORKFLOW_STARTED, "w1", {}),
            "/services/workflow",
            "w1",
            {"workflow_id": "w1"},
        ),
    ],
)
def test_factories_set_source_subject_and_data(factory, args, source, subject, data):
    event = factory(*args)
    assert event.type == args[0]
    assert event.source == source
    assert event.subject == subject
    assert event.data == data


def test_event_types_are_unique_and_namespaced():
    values = _event_type_values()
    assert len(values) == len(set(values))
    assert all(v.startswith("construction-enterprise-os.") for v in values)


@pytest.mark.parametrize("event_type", _event_type_values())
def test_every_event_type_has_a_topic(event_type):
    matches = [prefix for prefix in TOPIC_MAP if event_type.startswith(prefix + ".")]
    assert len(matches) == 1, (event_type, matches)
