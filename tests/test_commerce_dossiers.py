from copy import deepcopy
from uuid import uuid4
import pytest
from app.commerce_dossiers import PILOTS, build_dossiers


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
