"""Credential guard tests contain no real credentials and perform no network."""
import pytest

from tests.run_stripe_sandbox import load_profile


@pytest.mark.parametrize('prefix', ['sk_test_', 'rk_test_', 'rkcs_test_'])
def test_loads_only_explicit_test_profile_account(tmp_path, prefix):
    path = tmp_path / 'synthetic.toml'
    path.write_text('[isolated]\naccount_id="acct_SYNTHETIC"\ntest_mode_api_key="' +
                    prefix + 'synthetic_not_a_credential"\n', encoding='utf-8')
    assert load_profile(path, 'isolated', 'acct_SYNTHETIC') == prefix + 'synthetic_not_a_credential'


@pytest.mark.parametrize('credential,extra,account', [
    ('sk_live_never', '', 'acct_SYNTHETIC'), ('rkcs_live_never', '', 'acct_SYNTHETIC'),
    ('unknown_test_never', '', 'acct_SYNTHETIC'), ('sk_test_', '', 'acct_SYNTHETIC'),
    ('rkcs_test_synthetic', 'live_mode_api_key="sk_live_never"', 'acct_SYNTHETIC'),
    ('rkcs_test_synthetic', '', 'acct_OTHER'),
])
def test_unknown_live_mixed_or_wrong_account_refused(tmp_path, credential, extra, account):
    path = tmp_path / 'synthetic.toml'
    path.write_text('[isolated]\naccount_id="acct_SYNTHETIC"\ntest_mode_api_key="' + credential + '"\n' + extra,
                    encoding='utf-8')
    with pytest.raises(ValueError, match='isolated test-only'):
        load_profile(path, 'isolated', account)
