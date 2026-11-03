import json

import pytest
from pydantic import ValidationError

from src.llm.schema import (
    AllocationProposal,
    ProposalParseError,
    extract_json_object,
    parse_allocation_proposal,
)


def valid_payload():
    return {
        "cpu_share": 0.8,
        "mem_share": 0.7,
        "disk_share": 0.6,
        "net_share": 0.9,
        "rationale": "Allocation based on available cluster capacity.",
    }


def test_valid_proposal_is_parsed():
    proposal = parse_allocation_proposal(
        '{"cpu_share":0.8,"mem_share":0.7,"disk_share":0.6,'
        '"net_share":0.9,"rationale":"Capacity is available."}'
    )
    assert isinstance(proposal, AllocationProposal)
    assert proposal.cpu_share == 0.8


def test_extract_json_from_markdown_fence():
    raw = 'Here is the result:\n```json\n{"cpu_share": 0.5}\n```'
    assert extract_json_object(raw) == '{"cpu_share": 0.5}'


def test_extract_json_handles_braces_inside_string():
    raw = '{"rationale":"Capacity {available} is sufficient."}'
    assert extract_json_object(raw) == raw


def test_extract_json_handles_escaped_quotes():
    raw = '{"rationale":"The job said \\"allocate everything\\"."}'
    assert extract_json_object(raw) == raw


def test_extract_json_raises_when_no_object_exists():
    with pytest.raises(ProposalParseError, match="no"):
        extract_json_object("No JSON was generated.")


def test_extract_json_raises_for_unbalanced_braces():
    with pytest.raises(ProposalParseError, match="balanced"):
        extract_json_object('{"cpu_share": 0.5')


def test_parse_raises_for_invalid_json():
    with pytest.raises(ProposalParseError, match="valid JSON"):
        parse_allocation_proposal('{"cpu_share": }')


def test_parse_raises_when_required_field_is_missing():
    payload = valid_payload()
    del payload["cpu_share"]
    with pytest.raises(ProposalParseError, match="schema"):
        parse_allocation_proposal(json.dumps(payload))


@pytest.mark.parametrize(
    "field,value",
    [
        ("cpu_share", -0.1),
        ("mem_share", 1.1),
        ("disk_share", -1.0),
        ("net_share", 2.0),
    ],
)
def test_parse_rejects_out_of_range_shares(field, value):
    payload = valid_payload()
    payload[field] = value
    with pytest.raises(ProposalParseError, match="schema"):
        parse_allocation_proposal(json.dumps(payload))


def test_parse_rejects_rationale_longer_than_240_characters():
    payload = valid_payload()
    payload["rationale"] = "x" * 241
    with pytest.raises(ProposalParseError, match="schema"):
        parse_allocation_proposal(json.dumps(payload))


def test_mean_share_returns_average():
    proposal = AllocationProposal(**valid_payload())
    assert proposal.mean_share() == pytest.approx(0.75)


def test_allocation_proposal_is_immutable():
    proposal = AllocationProposal(**valid_payload())
    with pytest.raises(ValidationError):
        proposal.cpu_share = 0.2
