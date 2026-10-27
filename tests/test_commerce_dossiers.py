from copy import deepcopy
from hashlib import sha256
import json
from uuid import uuid4
import pytest
from app.commerce_dossiers import PILOTS, build_dossiers

REPLY_REVIEW_AS_OF = '2026-10-27T08:00:00Z'


@pytest.fixture
def evidence():
    slugs=list(PILOTS)+[f'synthetic-{n}' for n in range(35)]
    master={'recorded_at':'2026-10-24','counts':{'confirmed_fitments':0,'director_validated':0},'rows':[]}
    catalogue={'items':[]};copy={'products':[]};images={'counts':{'positive_commercial_image_permissions':0},'articles':[]}
    soyin={'findings':[]}
    for slug in slugs:
        identity=str(uuid4())
        master['rows'].append({'Identifiant produit':identity+' / '+slug,'Catégorie':'test',
            'Fournisseur':'CANDIDAT, pas retenu','Référence fournisseur':'NON CONFIRMÉE',
            'Restrictions de montage':'À confirmer','Lien produit fournisseur':'https://example.test',
            'Preuve de compatibilité':'local historical evidence'})
        catalogue['items'].append({'id':identity,'slug':slug,'name':slug,'sku':'TEST-'+slug,
            'price_cents':10000,'currency':'EUR','status':'draft','is_verified':False})
        copy['products'].append({'id':identity,'slug':slug,'assessment':{},'local_copy':{}})
        images['articles'].append({'slug':slug,'image_rights_status':'NOT_CONFIRMED'})
        soyin['findings'].append({'slug':slug,'source_values':{'supplier_sku':'CANDIDATE'},'issues':[]})
    return master,catalogue,copy,images,soyin


def test_forty_unique_dossiers_keep_missing_money_and_candidates_unconfirmed(evidence):
    result=build_dossiers(*evidence,observed_at='now')
    assert len(result['articles'])==40
    assert len({r['product_id'] for r in result['articles']})==40
    assert result['counts']['fully_verified']==0
    assert sorted(x['pilot_rank'] for x in result['articles'] if x['pilot_rank'])==[1,2,3,4,5]
    for row in result['articles']:
        assert row['supplier_selected'] is None and row['agent_responsible'] is None
        assert row['landed_cost_cents'] is None and row['gross_margin_cents'] is None
        assert row['commercial_image_permission_confirmed'] is False
        assert row['images_changed'] is False and row['sale_price_changed'] is False
        assert row['publication_status']=='draft'
        assert set(row['verification_statuses'].values())=={'PENDING_SUPPLIER','PENDING_HYPERSKU',
            'PENDING_COMPATIBILITY','PENDING_PRICING','PENDING_SHIPPING','PENDING_RIGHTS','BLOCKED'}


def test_blank_proposal_row_is_not_a_supplier_or_free_cost(evidence):
    evidence[-1]['findings'][0]['source_values']=None
    result=build_dossiers(*evidence,observed_at='now')
    assert result['counts']['candidate_soyin_named_skus']==39
    assert result['counts']['supplier_prices_confirmed']==0


@pytest.mark.parametrize('index,key',[(1,'items'),(2,'products'),(3,'articles')])
def test_missing_source_refuses_partial_report(evidence,index,key):
    evidence[index][key].pop()
    with pytest.raises(ValueError): build_dossiers(*evidence,observed_at='now')


def test_changed_confirmation_requires_review_not_hardcoded_old_counts(evidence):
    evidence[0]['counts']['confirmed_fitments']=1
    with pytest.raises(ValueError,match='Evidence has changed'):
        build_dossiers(*evidence,observed_at='now')


def test_duplicate_or_mismatched_identity_refused(evidence):
    evidence[1]['items'][0]['id']=str(uuid4())
    with pytest.raises(ValueError,match='identity drift'):
        build_dossiers(*evidence,observed_at='now')


def test_cli_blank_pilot_proposal_still_writes_complete_report(evidence,tmp_path,monkeypatch):
    import json
    import sys
    from scripts.build_commercial_dossiers import main
    master,catalogue,copy,images,soyin=evidence
    catalogue['recorded_at']='2026-10-24'
    soyin['findings'][0]['source_values']=None
    source=tmp_path/'evidence';output=tmp_path/'report'
    for relative,data in [('article-master-tracker.json',master),('catalogue/live-copy-snapshot.json',catalogue),
                          ('catalogue/product-copy-audit.json',copy),('images/rights-and-fidelity-40.json',images),
                          ('continuation/soyin-29-review.json',soyin)]:
        path=source/relative;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(data),encoding='utf-8')
    monkeypatch.setattr(sys,'argv',['dossiers','--source',str(source),'--output',str(output)])
    main()
    assert len(json.loads((output/'dossiers-40.json').read_text(encoding='utf-8'))['articles'])==40
    assert 'NON CONFIRMÉ / MANQUANT' in (output/'DOSSIERS.md').read_text(encoding='utf-8')


@pytest.fixture
def reply_review(evidence):
    rows = evidence[1]['items'][:2]
    review = {'recorded_at': '2026-10-27T07:05:00Z',
              'scope': 'candidate_supplier_evidence_only', 'articles': []}
    for number, row in enumerate(rows):
        ref = f'gmail-message:message{number}'
        review['articles'].append({
            'product_id': row['id'], 'slug': row['slug'], 'supplier_name': 'Candidate supplier',
            'candidate_reference': 'CANDIDATE' if number == 0 else None,
            'reply_status': 'RESPONSE_INCOMPLETE',
            'sources': [{'message_id': f'message{number}', 'thread_id': 'thread1',
                         'received_at': '2026-10-26T02:19:01Z', 'evidence_ref': ref}],
            'confirmed_candidate_facts': [{
                'fact': 'steering_restriction' if number == 0 else 'unit_shipping_claim',
                'value': 'LHD only; RHD excluded' if number == 0 else 'Website unit price includes shipping, no dated France quote',
                'evidence_refs': [ref],
                'scope': 'candidate_only' if number == 0 else 'supplier_generic_claim'}],
            'documents': [] if number == 0 else [{
                'filename': 'User Manual.pdf', 'bytes': 10616832, 'sha256': '8a' * 32,
                'status': 'UNREADABLE_INCOMPLETE', 'evidence_ref': ref,
                'checks': ['Unexpected EOF; no usable technical content']}],
            'unresolved': ['Exact supplied SKU, rights, fitment, price and warranty unconfirmed'],
            'next_action': 'Request complete manual and exact model; no order authorized',
        })
    return review


def test_optional_reply_never_promotes_a_candidate_to_product_or_money(evidence, reply_review):
    original = deepcopy((evidence, reply_review))
    baseline = build_dossiers(*evidence, observed_at='now')
    result = build_dossiers(*evidence, observed_at='now', reply_review=reply_review,
                            reply_review_as_of=REPLY_REVIEW_AS_OF)
    assert (evidence, reply_review) == original
    assert len(result['articles']) == 40
    assert result['counts']['candidate_reply_articles'] == 2
    assert result['counts']['documents_unreadable'] == 1
    counts = dict(result['counts'])
    counts.pop('candidate_reply_articles')
    counts.pop('documents_unreadable')
    assert counts == baseline['counts']
    for before, after in zip(baseline['articles'], result['articles']):
        comparison = deepcopy(after)
        if 'candidate_supplier_replies' in comparison:
            reply = comparison.pop('candidate_supplier_replies')[0]
            assert reply['reply_status'] == 'RESPONSE_INCOMPLETE'
            assert comparison['sources'].pop('supplier_reply_review')['recorded_at'] == reply_review['recorded_at']
            assert comparison['next_action'] == reply['next_action']
            comparison['next_action'] = before['next_action']
        assert comparison == before
        assert after['supplier_selected'] is None
        assert after['supplier_unit_cost_cents'] is after['shipping_confirmed_cents'] is None
        assert after['compatibility_verified'] is False
        assert after['commercial_image_permission_confirmed'] is False
    assert result['source_digest_sha256'] != baseline['source_digest_sha256']
    reply_review['articles'][0]['confirmed_candidate_facts'][0]['value'] += ' updated'
    assert build_dossiers(*evidence, observed_at='now', reply_review=reply_review,
                          reply_review_as_of=REPLY_REVIEW_AS_OF)['source_digest_sha256'] != result['source_digest_sha256']


def test_default_output_and_fingerprint_are_backward_compatible(evidence):
    implicit = build_dossiers(*evidence, observed_at='now')
    assert implicit == build_dossiers(*evidence, observed_at='now', reply_review=None)
    assert implicit == build_dossiers(*evidence, observed_at='now', reply_review_as_of='unused without supplement')
    expected_digest = sha256(json.dumps(list(evidence), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    assert implicit['source_digest_sha256'] == expected_digest
    assert 'candidate_reply_articles' not in implicit['counts']
    assert all('candidate_supplier_replies' not in row for row in implicit['articles'])


def test_report_objects_do_not_alias_source_evidence(evidence, reply_review):
    original = deepcopy((evidence, reply_review))
    result = build_dossiers(*evidence, observed_at='now', reply_review=reply_review,
                            reply_review_as_of=REPLY_REVIEW_AS_OF)
    for row in result['articles']:
        row['candidate_soyin']['source_values']['supplier_sku'] = 'not the source'
        row['title_description_review']['changed'] = True
        row['proposed_copy']['changed'] = True
        if row.get('candidate_supplier_replies'):
            row['candidate_supplier_replies'][0]['sources'][0]['message_id'] = 'not the source'
    assert (evidence, reply_review) == original


@pytest.mark.parametrize('problem', ['mismatch_id', 'unknown_slug', 'duplicate_article',
    'duplicate_source', 'duplicate_fact', 'duplicate_document', 'unbound_fact', 'unbound_document',
    'invalid_source_ref', 'empty_fact_proof', 'invalid_fact_scope', 'invalid_scope_type',
    'approved_reply', 'readable_doc_status', 'short_hash', 'hash_type', 'boolean_bytes',
    'negative_bytes', 'non_string_fact', 'undated_review', 'undated_message', 'facts_not_list'])
def test_candidate_review_rejects_inconsistent_or_unbound_evidence(evidence, reply_review, problem):
    article = reply_review['articles'][0]
    document_article = reply_review['articles'][1]
    fact = article['confirmed_candidate_facts'][0]
    document = document_article['documents'][0]
    if problem == 'mismatch_id': article['product_id'] = str(uuid4())
    elif problem == 'unknown_slug': article['slug'] = 'unknown-product'
    elif problem == 'duplicate_article': reply_review['articles'].append(deepcopy(article))
    elif problem == 'duplicate_source': article['sources'].append(deepcopy(article['sources'][0]))
    elif problem == 'duplicate_fact': article['confirmed_candidate_facts'].append(deepcopy(fact))
    elif problem == 'duplicate_document': document_article['documents'].append(deepcopy(document))
    elif problem == 'unbound_fact': fact['evidence_refs'] = ['gmail-message:unrelated']
    elif problem == 'unbound_document': document['evidence_ref'] = article['sources'][0]['evidence_ref']
    elif problem == 'invalid_source_ref': article['sources'][0]['evidence_ref'] = 'gmail-message:other'
    elif problem == 'empty_fact_proof': fact['evidence_refs'] = []
    elif problem == 'invalid_fact_scope': fact['scope'] = 'confirmed_product'
    elif problem == 'invalid_scope_type': fact['scope'] = {}
    elif problem == 'approved_reply': article['reply_status'] = 'APPROVED'
    elif problem == 'readable_doc_status': document['status'] = 'VALIDATED'
    elif problem == 'short_hash': document['sha256'] = '8a'
    elif problem == 'hash_type': document['sha256'] = 1
    elif problem == 'boolean_bytes': document['bytes'] = True
    elif problem == 'negative_bytes': document['bytes'] = -1
    elif problem == 'non_string_fact': fact['value'] = True
    elif problem == 'undated_review': reply_review['recorded_at'] = '2026-10-27'
    elif problem == 'undated_message': article['sources'][0]['received_at'] = '2026-10-27T07:05:00'
    elif problem == 'facts_not_list': article['confirmed_candidate_facts'] = {}
    with pytest.raises(ValueError):
        build_dossiers(*evidence, observed_at='now', reply_review=reply_review,
                       reply_review_as_of=REPLY_REVIEW_AS_OF)


@pytest.mark.parametrize('location', ['review', 'article', 'fact', 'source', 'document'])
@pytest.mark.parametrize('field', ['price_cents', 'compatibility_verified', 'supplier_selected'])
def test_closed_schema_rejects_unexpected_money_or_approval_fields(evidence, reply_review, location, field):
    first = reply_review['articles'][0]
    target = {'review': reply_review, 'article': first,
              'fact': first['confirmed_candidate_facts'][0], 'source': first['sources'][0],
              'document': reply_review['articles'][1]['documents'][0]}[location]
    target[field] = True
    with pytest.raises(ValueError, match='unexpected fields'):
        build_dossiers(*evidence, observed_at='now', reply_review=reply_review,
                       reply_review_as_of=REPLY_REVIEW_AS_OF)


def test_markdown_distinguishes_candidate_restrictions_generic_shipping_and_invalid_documents(evidence, reply_review):
    from scripts.build_commercial_dossiers import render_markdown
    result = build_dossiers(*evidence, observed_at='now', reply_review=reply_review,
                            reply_review_as_of=REPLY_REVIEW_AS_OF)
    markdown = render_markdown(result)
    assert 'NON VALIDÉE POUR LE PRODUIT TYMOTORS' in markdown
    assert 'LHD only; RHD excluded' in markdown
    assert 'supplier\\_generic\\_claim' in markdown
    assert 'ni un coût unitaire ni un devis de port vers la France' in markdown
    assert 'INCOMPLET / ILLISIBLE' in markdown
    assert 'User Manual.pdf' in markdown and '8a' * 32 in markdown
    assert 'Aucune caractéristique déduite' in markdown
    assert '2026-10-26T02:19:01Z' in markdown
    reply_review['articles'][0]['confirmed_candidate_facts'][0]['value'] = '<script>bad</script> | [approval](bad)'
    rendered = render_markdown(build_dossiers(*evidence, observed_at='now', reply_review=reply_review,
                                             reply_review_as_of=REPLY_REVIEW_AS_OF))
    assert '<script>' not in rendered
    assert '&lt;script&gt;' in rendered and '\\[approval\\]' in rendered


def test_cli_optional_reply_review_is_used_without_live_request(evidence, reply_review, tmp_path, monkeypatch):
    from datetime import datetime, timezone
    import sys
    from scripts import build_commercial_dossiers as cli
    master, catalogue, copy, images, soyin = evidence
    catalogue['recorded_at'] = '2026-10-24T14:07:09Z'
    source, output = tmp_path / 'evidence', tmp_path / 'report'
    for relative, data in [('article-master-tracker.json', master), ('catalogue/live-copy-snapshot.json', catalogue),
                           ('catalogue/product-copy-audit.json', copy), ('images/rights-and-fidelity-40.json', images),
                           ('continuation/soyin-29-review.json', soyin)]:
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding='utf-8')
    supplement = tmp_path / 'reply-review.json'
    supplement.write_text(json.dumps(reply_review), encoding='utf-8')
    def no_network(*args, **kwargs):
        raise AssertionError('Historical CLI must not call a live API')
    class FixedClock:
        @staticmethod
        def now(tz):
            assert tz is timezone.utc
            return datetime.fromisoformat(REPLY_REVIEW_AS_OF.replace('Z', '+00:00'))
    monkeypatch.setattr(cli, 'urlopen', no_network)
    monkeypatch.setattr(cli, 'datetime', FixedClock)
    monkeypatch.setattr(sys, 'argv', ['dossiers', '--source', str(source), '--output', str(output),
                                    '--reply-review', str(supplement),'--historical-scope'])
    cli.main()
    result = json.loads((output / 'dossiers-40.json').read_text(encoding='utf-8'))
    assert result['counts']['articles'] == 40
    assert result['counts']['candidate_reply_articles'] == 2
    assert result['counts']['documents_unreadable'] == 1
    assert result['counts']['fully_verified'] == 0
    enriched = next(row for row in result['articles'] if row.get('candidate_supplier_replies'))
    assert enriched['sources']['supplier_reply_review']['checked_as_of'] == '2026-10-27T08:00:00+00:00'
    assert 'INCOMPLET / ILLISIBLE' in (output / 'DOSSIERS.md').read_text(encoding='utf-8')


@pytest.mark.parametrize('received_at', ['2099-01-01T00:00:00Z', '2026-10-27T07:05:01Z'])
def test_message_cannot_be_received_after_its_reply_review(evidence, reply_review, received_at):
    reply_review['articles'][0]['sources'][0]['received_at'] = received_at
    with pytest.raises(ValueError, match='received_at is after'):
        build_dossiers(*evidence, observed_at='2026-10-23T00:00:00Z', reply_review=reply_review,
                       reply_review_as_of=REPLY_REVIEW_AS_OF)


@pytest.mark.parametrize('recorded_at', ['2099-01-01T00:00:00Z', '2026-10-27T08:00:01Z'])
def test_reply_review_cannot_be_future_dated_against_the_explicit_clock(evidence, reply_review, recorded_at):
    reply_review['recorded_at'] = recorded_at
    with pytest.raises(ValueError, match='after the explicit review clock'):
        build_dossiers(*evidence, observed_at='2099-12-31T00:00:00Z', reply_review=reply_review,
                       reply_review_as_of=REPLY_REVIEW_AS_OF)


@pytest.mark.parametrize('clock', [None, '', 'not-a-date', '2026-10-27',
                                  '2026-10-27T08:00:00', True, {}, 2026])
def test_supplement_requires_a_separate_valid_timezone_aware_review_clock(evidence, reply_review, clock):
    with pytest.raises(ValueError, match='clock'):
        build_dossiers(*evidence, observed_at='2026-10-27T08:00:00Z', reply_review=reply_review,
                       reply_review_as_of=clock)


def test_omitted_review_clock_does_not_fall_back_to_the_price_observation(evidence, reply_review):
    with pytest.raises(ValueError, match='explicit reply review clock'):
        build_dossiers(*evidence, observed_at=REPLY_REVIEW_AS_OF, reply_review=reply_review)


def test_caller_cannot_put_a_trusted_clock_in_the_untrusted_json(evidence, reply_review):
    reply_review['reply_review_as_of'] = '2099-01-01T00:00:00Z'
    with pytest.raises(ValueError, match='unexpected fields'):
        build_dossiers(*evidence, observed_at='now', reply_review=reply_review,
                       reply_review_as_of=REPLY_REVIEW_AS_OF)


def test_equivalent_offsets_compare_instants_and_allow_exact_boundary(evidence, reply_review):
    reply_review['recorded_at'] = '2026-10-27T08:05:00+01:00'
    for article in reply_review['articles']:
        article['sources'][0]['received_at'] = '2026-10-27T03:05:00-04:00'
    result = build_dossiers(*evidence, observed_at='2026-10-23T00:00:00Z', reply_review=reply_review,
                            reply_review_as_of='2026-10-27T07:05:00Z')
    assert result['counts']['candidate_reply_articles'] == 2


def test_price_observation_is_not_the_review_clock_and_may_be_older(evidence, reply_review):
    historical = '2026-10-23T00:00:00Z'
    result = build_dossiers(*evidence, observed_at=historical, reply_review=reply_review,
                            reply_review_as_of=REPLY_REVIEW_AS_OF)
    assert all(row['sale_price_observed_at'] == historical for row in result['articles'])
    assert result['counts']['candidate_reply_articles'] == 2
    assert result['counts']['fully_verified'] == 0
    assert result['counts']['supplier_prices_confirmed'] == 0


def test_supplement_fingerprint_also_records_the_explicit_review_clock(evidence, reply_review):
    first = build_dossiers(*evidence, observed_at='historical', reply_review=reply_review,
                           reply_review_as_of=REPLY_REVIEW_AS_OF)
    second = build_dossiers(*evidence, observed_at='historical', reply_review=reply_review,
                            reply_review_as_of='2026-10-27T09:00:00Z')
    assert first['source_digest_sha256'] != second['source_digest_sha256']
    assert first['counts'] == second['counts']


def test_current_owner_scope_defers_photo_work_without_grant_or_data_mutation(evidence):
    from app.commerce_dossiers import apply_owner_execution_scope,ORIGINAL_SUPPLIERS
    historical=build_dossiers(*evidence,observed_at='historical')
    original=deepcopy(historical)
    current=apply_owner_execution_scope(historical)
    assert historical==original
    assert current['execution_policy']['photo_certification_required'] is False
    assert current['execution_policy']['publication_authorized'] is False
    assert current['counts']['original_supplier_partners']==3
    assert current['counts']['article_offer_mappings_confirmed']==0
    assert 'selected_suppliers_confirmed' not in current['counts']
    assert current['counts']['photo_reviews_deferred']==40
    assert 'PENDING_RIGHTS' not in current['counts']['pending_by_dimension']
    for before,after in zip(historical['articles'],current['articles']):
        assert after['active_supplier_scope']==list(ORIGINAL_SUPPLIERS)
        assert after['verification_statuses']['image_rights']=='DEFERRED_BY_OWNER'
        assert all(b['code']!='IMAGE_RIGHTS' for b in after['blockers'])
        for key in ('product_id','slug','sku','image_rights_status','commercial_image_permission_confirmed',
                    'images_changed','sale_price_changed','supplier_selected','compatibility_verified',
                    'supplier_unit_cost_cents','supplier_currency','shipping_confirmed_cents','landed_cost_cents',
                    'gross_margin_cents','publication_status','candidate_soyin'):
            assert after[key]==before[key]
        assert after['sources']['historical_supplier']==before['sources']['supplier']
        assert after['historical_source_reference_candidates']==before['source_reference_candidates']


def test_current_scope_preserves_explicit_refusal(evidence):
    from app.commerce_dossiers import apply_owner_execution_scope
    evidence[3]['articles'][0]['image_rights_status']='REFUSED'
    current=apply_owner_execution_scope(build_dossiers(*evidence,observed_at='historical'))
    row=next(a for a in current['articles'] if a['image_rights_status']=='REFUSED')
    assert any(b['code']=='IMAGE_REFUSAL' for b in row['blockers'])
    assert row['commercial_image_permission_confirmed'] is False


def test_external_retailer_replies_are_history_not_active_procurement(evidence,reply_review):
    from app.commerce_dossiers import apply_owner_execution_scope
    original=build_dossiers(*evidence,observed_at='historical',reply_review=reply_review,
        reply_review_as_of=REPLY_REVIEW_AS_OF)
    current=apply_owner_execution_scope(original)
    assert current['counts']['historical_candidate_reply_articles']==2
    assert 'candidate_reply_articles' not in current['counts']
    for a in current['articles']:
        assert 'candidate_supplier_replies' not in a
        assert 'droits' not in a['next_action'].lower()
    assert sum(bool(a.get('historical_candidate_supplier_replies')) for a in current['articles'])==2
    assert current['source_digest_sha256']==original['source_digest_sha256']
    assert current['execution_digest_sha256']!=original['source_digest_sha256']


def test_missing_soyin_sku_never_replaced_with_retailer_reference(evidence):
    from app.commerce_dossiers import apply_owner_execution_scope
    evidence[-1]['findings'][0]['source_values']=None
    current=apply_owner_execution_scope(build_dossiers(*evidence,observed_at='historical'))
    row=next(a for a in current['articles'] if a['slug']==PILOTS[0])
    assert row['candidate_soyin']['source_values'] is None
    assert 'Retrouver la référence' in row['next_action']
    assert row['supplier_selected'] is None


def test_current_markdown_prioritizes_non_photo_work(evidence):
    from app.commerce_dossiers import apply_owner_execution_scope
    from scripts.build_commercial_dossiers import render_markdown
    current=apply_owner_execution_scope(build_dossiers(*evidence,observed_at='historical'))
    text=render_markdown(current)
    assert 'Trois fournisseurs initiaux uniquement' in text
    assert 'montage, droits, devis' not in text
    assert 'Prochaine action : Soyintech' in text


def test_scope_cannot_be_applied_twice(evidence):
    from app.commerce_dossiers import apply_owner_execution_scope
    current=apply_owner_execution_scope(build_dossiers(*evidence,observed_at='historical'))
    with pytest.raises(ValueError): apply_owner_execution_scope(current)
