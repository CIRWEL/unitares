from src.services.identity_payloads import (
    build_identity_diag_payload,
    build_identity_response_data,
    build_onboard_response_data,
)


def test_build_identity_response_data_verbose_includes_continuity_context():
    payload = build_identity_response_data(
        agent_uuid="uuid-123",
        agent_id="agent-123",
        display_name="Tester",
        client_session_id="sess-123",
        continuity_source="client_session_id",
        continuity_support={"enabled": True},
        continuity_token="token-abc",
        identity_status="resumed",
        model_type="gpt",
        resumed=True,
        session_continuity=None,
        verbose=True,
    )

    assert payload["agent_id"] == "agent-123"
    assert payload["agent_uuid"] == "uuid-123"
    assert payload["public_agent_id"] == "agent-123"
    assert payload["continuity_token"] == "token-abc"
    assert payload["session_continuity"]["continuity_token"] == "token-abc"
    assert payload["quick_reference"]["for_strong_resume"] == "token-abc"


def test_build_identity_diag_payload_keeps_fast_path_shape_consistent():
    payload = build_identity_diag_payload(
        agent_uuid="uuid-123",
        agent_id="agent-123",
        display_name="Tester",
        client_session_id="sess-123",
        continuity_source="client_session_id",
        continuity_support={"enabled": True},
        continuity_token="token-abc",
        identity_status="archived",
    )

    assert payload["identity_status"] == "archived"
    assert payload["bound_identity"]["uuid"] == "uuid-123"
    assert payload["continuity_token"] == "token-abc"
    assert payload["identity_handles"]["canonical_join_key"] == "agent_uuid"


def test_build_onboard_response_data_includes_thread_and_workflow_when_verbose():
    payload = build_onboard_response_data(
        agent_uuid="uuid-123",
        structured_agent_id="agent-123",
        agent_label="Tester",
        stable_session_id="sess-123",
        is_new=True,
        force_new=False,
        client_hint="chatgpt",
        was_archived=False,
        trajectory_result={"genesis_stored": True},
        parent_agent_id=None,
        thread_context={
            "is_root": True,
            "thread_id": "thread-1234567890",
            "position": 1,
            "honest_message": "Root node",
        },
        verbose=True,
        continuity_source="continuity_token",
        continuity_support={"enabled": True},
        continuity_token="token-abc",
        system_activity={"agents": {"active": 1}},
        tool_mode_info={"current_mode": "lite"},
    )

    assert payload["continuity_token"] == "token-abc"
    assert payload["thread_context"]["thread_id"] == "thread-1234567890"
    assert payload["workflow"]["step_1"] == "Copy client_session_id from above"
    assert payload["tool_mode"]["current_mode"] == "lite"
    assert payload["trajectory"]["trust_tier"]["tier"] == 1
    assert payload["agent_uuid"] == "uuid-123"
    assert payload["public_agent_id"] == "agent-123"
