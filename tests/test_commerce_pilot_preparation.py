from copy import deepcopy
from datetime import datetime, timezone
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.commerce_dossiers import PILOTS, apply_owner_execution_scope, build_dossiers
from app.commerce_models import OfferInput, ShippingRateInput, VariantInput
from app.commerce_pilot_preparation import prepare_pilot_catalogue
from tests.test_commerce_dossiers import evidence  # Reuse the existing lightweight forty-row fixture.


AS_OF = '2026-10-28T08:00:00Z'


@pytest.fixture
def pilot_inputs(evidence):
    master, catalogue, copy_review, images, soyin = evidence
    soyin.update(received_at='2026-10-23T09:00:54Z', received_message_id='message1', sha256='ab' * 32)
    for rank, slug in enumerate(PILOTS, 1):
        proposal = next(row for row in soyin['findings'] if row['slug'] == slug)
        proposal.update(sheet='Sheet1', row=rank + 1,
                        cells={'sku': f'D{rank + 1}', 'material': f'E{rank + 1}', 'fitment': f'F{rank + 1}'},
                        exact_same_product_proved=False, selected_supplier_variant=False,
                        fitment_confirmed_for_tymotors=False, price_quote_present=False)
        proposal['source_values'].update(internal_code_raw=slug, material='PP' if rank == 1 else 'ABS',
                                        fitment='Candidate declaration, actual mounting unconfirmed',
                                        offered_url='https://example.test/candidate' if rank % 2 else None)
        reviewed = next(row for row in copy_review['products'] if row['slug'] == slug)
        reviewed['local_copy'] = {'title': 'Projet ' + slug, 'subtitle': 'Montage à confirmer',
                                  'description': 'Référence réellement approvisionnée et montage à confirmer.'}
    dossiers = apply_owner_execution_scope(build_dossiers(*evidence, observed_at='2026-10-27T14:03:29Z'))
    return dossiers, soyin


def test_prepares_exactly_five_draft_only_packets_and_keeps_candidate_separate(pilot_inputs):
    dossiers, soyin = pilot_inputs
    before = deepcopy(pilot_inputs)
    result = prepare_pilot_catalogue(*pilot_inputs, prepared_at=AS_OF)
    assert pilot_inputs == before
    assert [row['slug'] for row in result['pilots']] == list(PILOTS)
    assert result['summary']['pilots'] == 5
    assert result['summary']['commercially_verified_pilots'] == 0
    assert result['summary']['confirmed_actual_product_fitments'] == 0
    for row in result['pilots']:
        source = next(article for article in dossiers['articles'] if article['slug'] == row['slug'])
        choice = row['supplier_choice']
        assert choice['candidate_reference'] == source['candidate_soyin']['source_values']['supplier_sku']
        assert choice['selected_reference'] is choice['selected_supplier_id'] is choice['selected_variant'] is None
        assert row['candidate_declarations']['scope'] == 'supplier_candidate_only_not_actual_product_confirmation'
        assert row['actual_product_fitment']['confirmed_rules'] == []
        assert row['actual_product_fitment']['compatibility_verified'] is False
        assert row['actual_product_fitment']['extensions_not_proved']
        assert row['catalogue_copy']['patch'] == {}
        assert row['catalogue_copy']['description'] == source['proposed_copy']['description']
        assert row['safety']['photo_review'] == 'DEFERRED_BY_OWNER'
        assert row['safety']['publication_authorized'] is False
        assert row['safety']['commercially_verified'] is False
        variant = VariantInput.model_validate(row['draft_variant_import_preview']['data'])
        assert variant.status == 'draft' and variant.stock == 0 and not variant.is_verified
        assert variant.is_default is False and variant.evidence_ref is None
        assert variant.attributes == {} and variant.compatibility_ids == []
        assert variant.price_cents == source['sale_price_cents_observed']
        assert row['public_price_observation']['changed'] is False
        assert row['public_price_observation']['price_approval'] is False
        assert row['public_price_observation']['observed_at'] == source['sale_price_observed_at']
        assert row['draft_variant_import_preview']['import_allowed'] is False


def test_offer_shipping_remain_explicitly_incomplete_instead_of_filling_unknowns(pilot_inputs):
    result = prepare_pilot_catalogue(*pilot_inputs, prepared_at=AS_OF)
    for row in result['pilots']:
        offer, shipping = row['candidate_offer_template'], row['direct_france_shipping_template']
        assert offer['schema_valid'] is shipping['schema_valid'] is False
        assert offer['import_allowed'] is shipping['import_allowed'] is False
        assert {'supplier_id', 'variant_id', 'supplier_variant', 'currency', 'moq'} <= set(offer['missing_or_invalid_fields'])
        assert offer['data']['availability'] == 'unknown' and offer['data']['available_quantity'] is None
        assert offer['data']['unit_cost_cents'] is offer['data']['recoverable_tax_cents'] is None
        assert offer['data']['fx_rate'] is offer['data']['valid_until'] is None
        assert offer['data']['verification_state'] == 'pending' and offer['data']['is_primary'] is False
        assert {'offer_id', 'mode', 'min_quantity', 'max_quantity', 'currency'} <= set(shipping['missing_or_invalid_fields'])
        assert shipping['data']['country'] == 'FR' and shipping['data']['multi_variant_policy'] == 'unknown'
        assert shipping['data']['shipping_cost_cents'] is shipping['data']['customer_shipping_cents'] is None
        assert shipping['data']['import_duty_cents'] is shipping['data']['goods_tax_bps'] is None
        with pytest.raises(ValidationError):
            OfferInput.model_validate(offer['data'])
        with pytest.raises(ValidationError):
            ShippingRateInput.model_validate(shipping['data'])


def test_mutating_export_does_not_mutate_dossiers_original_reply_or_global_profiles(pilot_inputs):
    before = deepcopy(pilot_inputs)
    result = prepare_pilot_catalogue(*pilot_inputs, prepared_at=AS_OF)
    result['pilots'][0]['actual_product_fitment']['restrictions_to_confirm'].clear()
    result['pilots'][0]['candidate_declarations']['issues'].append('changed')
    result['pilots'][0]['catalogue_copy']['description'] = 'changed'
    assert pilot_inputs == before
    assert prepare_pilot_catalogue(*pilot_inputs, prepared_at=AS_OF)['pilots'][0]['actual_product_fitment']['restrictions_to_confirm']


@pytest.mark.parametrize('problem', ['missing_article', 'duplicate_slug', 'duplicate_id', 'nonpilot_bad_uuid',
    'missing_pilot', 'wrong_rank', 'boolean_rank', 'wrong_supplier_scope', 'publication_permission',
    'photo_scope_changed', 'selected_supplier', 'verified_fitment', 'approved_product', 'active_product',
    'known_cost', 'free_shipping_claim', 'candidate_drift', 'candidate_code_drift', 'wrong_source_cell',
    'missing_candidate_sku', 'candidate_material_missing', 'missing_copy', 'boolean_price', 'missing_internal_sku',
    'future_observation', 'future_reply', 'naive_clock', 'future_price', 'missing_message', 'invalid_attachment_hash'])
def test_rejects_identity_evidence_or_approval_drift(pilot_inputs, problem):
    dossiers, soyin = pilot_inputs
    first = next(row for row in dossiers['articles'] if row['slug'] == PILOTS[0])
    original = next(row for row in soyin['findings'] if row['slug'] == PILOTS[0])
    if problem == 'missing_article': dossiers['articles'].pop()
    elif problem == 'duplicate_slug': dossiers['articles'].append(deepcopy(first))
    elif problem == 'duplicate_id': dossiers['articles'][-1]['product_id'] = first['product_id']
    elif problem == 'nonpilot_bad_uuid': dossiers['articles'][-1]['product_id'] = 'invalid'
    elif problem == 'missing_pilot': first['pilot_rank'] = None
    elif problem == 'wrong_rank': first['pilot_rank'] = 2
    elif problem == 'boolean_rank': first['pilot_rank'] = True
    elif problem == 'wrong_supplier_scope': dossiers['execution_policy']['original_suppliers'].append('Other supplier')
    elif problem == 'publication_permission': dossiers['execution_policy']['publication_authorized'] = True
    elif problem == 'photo_scope_changed': dossiers['execution_policy']['photo_review'] = 'APPROVED'
    elif problem == 'selected_supplier': first['supplier_selected'] = str(uuid4())
    elif problem == 'verified_fitment': first['compatibility_verified'] = True
    elif problem == 'approved_product': first['catalogue_verified_observed'] = True
    elif problem == 'active_product': first['publication_status'] = 'active'
    elif problem == 'known_cost': first['supplier_unit_cost_cents'] = 100
    elif problem == 'free_shipping_claim': first['shipping_confirmed_cents'] = 0
    elif problem == 'candidate_drift': original['source_values']['supplier_sku'] = 'other SKU'
    elif problem == 'candidate_code_drift':
        original['source_values']['internal_code_raw'] = 'other-article'
        first['candidate_soyin'] = deepcopy(original)
    elif problem == 'wrong_source_cell':
        original['cells']['sku'] = 'D99'
        first['candidate_soyin'] = deepcopy(original)
    elif problem == 'missing_candidate_sku':
        original['source_values']['supplier_sku'] = None
        first['candidate_soyin'] = deepcopy(original)
    elif problem == 'candidate_material_missing':
        original['source_values']['material'] = None
        first['candidate_soyin'] = deepcopy(original)
    elif problem == 'missing_copy': first['proposed_copy']['description'] = ''
    elif problem == 'boolean_price': first['sale_price_cents_observed'] = True
    elif problem == 'missing_internal_sku': first['sku'] = None
    elif problem == 'future_observation': dossiers['observed_at'] = '2099-01-01T00:00:00Z'
    elif problem == 'future_reply': soyin['received_at'] = '2099-01-01T00:00:00Z'
    elif problem == 'naive_clock':
        with pytest.raises(ValueError):
            prepare_pilot_catalogue(*pilot_inputs, prepared_at='2026-10-28T08:00:00')
        return
    elif problem == 'future_price': first['sale_price_observed_at'] = '2099-01-01T00:00:00Z'
    elif problem == 'missing_message': soyin['received_message_id'] = None
    elif problem == 'invalid_attachment_hash': soyin['sha256'] = 'invalid'
    with pytest.raises(ValueError):
        prepare_pilot_catalogue(*pilot_inputs, prepared_at=AS_OF)


def test_dated_provenance_and_fingerprint_follow_inputs_not_new_claims(pilot_inputs):
    first = prepare_pilot_catalogue(*pilot_inputs, prepared_at=AS_OF)
    pilot_inputs[0]['articles'][0]['next_action'] += ' changed'
    second = prepare_pilot_catalogue(*pilot_inputs, prepared_at=AS_OF)
    assert first['sources']['dossiers_canonical_sha256'] != second['sources']['dossiers_canonical_sha256']
    assert first['sources']['soyin_attachment_sha256'] == 'ab' * 32
    assert first['source_observed_at'] == '2026-10-27T14:03:29Z'
    assert first['pilots'][0]['candidate_declarations']['reply_received_at'] == '2026-10-23T09:00:54Z'
    assert first['pilots'][0]['candidate_declarations']['reference_evidence'].endswith('#Sheet1!D2')


def test_local_cli_exports_five_packets_without_network_and_refuses_overwrite(pilot_inputs, tmp_path, monkeypatch, capsys):
    import sys
    import urllib.request
    from scripts import prepare_commercial_pilots as cli
    dossiers, soyin = pilot_inputs
    source, reply = tmp_path / 'dossiers.json', tmp_path / 'soyin.json'
    source.write_text(json.dumps(dossiers), encoding='utf-8')
    reply.write_text(json.dumps(soyin), encoding='utf-8')
    output = tmp_path / 'new-pilot-prep'
    class FixedClock:
        @staticmethod
        def now(tz):
            assert tz is timezone.utc
            return datetime.fromisoformat(AS_OF.replace('Z', '+00:00'))
    def forbid_network(*args, **kwargs):
        raise AssertionError('Pilot preparation may not call external services')
    monkeypatch.setattr(cli, 'datetime', FixedClock)
    monkeypatch.setattr(urllib.request, 'urlopen', forbid_network)
    monkeypatch.setattr(sys, 'argv', ['pilots', '--dossiers', str(source), '--soyin', str(reply), '--output', str(output)])
    cli.main()
    packet = json.loads((output / 'pilots-5.json').read_text(encoding='utf-8'))
    assert len(packet['pilots']) == 5
    assert packet['summary']['imports_executed'] == 0
    assert packet['sources']['input_file_sha256']['dossiers']
    markdown = (output / 'PILOTS.md').read_text(encoding='utf-8')
    assert 'NON IMPORTABLE' in markdown and 'sans réécriture' in markdown
    assert 'NON PROUVÉE, pas incompatibilité attestée' in markdown
    assert 'Message' not in capsys.readouterr().out
    before = (output / 'pilots-5.json').read_bytes()
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    assert (output / 'pilots-5.json').read_bytes() == before
    assert json.loads(source.read_text(encoding='utf-8')) == dossiers


def test_cli_has_no_live_import_or_send_option(tmp_path, monkeypatch):
    import sys
    from scripts.prepare_commercial_pilots import main
    monkeypatch.setattr(sys, 'argv', ['pilots', '--dossiers', 'unused', '--soyin', 'unused',
                                    '--output', str(tmp_path / 'unused'), '--live'])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert not (tmp_path / 'unused').exists()
