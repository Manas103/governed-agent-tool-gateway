from gateway.corpus import generate_oracle_corpus
from gateway.gateway_core import ProposalResult


def test_oracle_corpus_every_seeded_mistake_is_flagged_and_every_clean_case_is_not(gateway, issuer, registry, session):
    corpus = generate_oracle_corpus(
        session, registry, issuer, n=500, seed=7, mistake_rate=0.1,
        n_users=50, n_boards=50, n_pins=400, n_campaigns=30,
    )
    assert any(item.is_mistake for item in corpus)
    assert any(not item.is_mistake for item in corpus)

    for item in corpus:
        result = gateway.call(item.token, item.tool, item.candidate_params)
        assert isinstance(result, ProposalResult)
        if item.is_mistake:
            assert result.oracle_ok is False, (item.tool, item.candidate_params, item.mistake_kind)
            assert result.oracle_reason is not None, "every disagreement must surface a reason to the approver"
        else:
            assert result.oracle_ok is True, (item.tool, item.candidate_params)
