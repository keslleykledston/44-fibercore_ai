import unittest
from dataclasses import replace
from starter.expert_policy import (
    ProfileObservation, canonical_hash, validate_edit,
    semantic_diff, resolve_strategy, in_place_allowed,
)


class ExpertPolicyTests(unittest.TestCase):
    def setUp(self):
        self.obs = ProfileObservation('isp-a', 'olt-1', 'R015', 'GPON-A', 'fresh',
                                      'h12345678', 126, {'customer_vlan': 200, 'tagging': 'tagged'})
        self.diff = semantic_diff(self.obs, {'customer_vlan': 200, 'tagging': 'tagged'})
        self.base = dict(requested='reuse_exact', observation=self.obs, current_tenant='isp-a',
                         current_olt='olt-1', current_firmware='R015', current_card='GPON-A',
                         source_fingerprint='h12345678', diff=self.diff, certified_read=True)

    def test_stable_fingerprint(self):
        self.assertEqual(canonical_hash({'a': 1, 'b': 2}), canonical_hash({'b': 2, 'a': 1}))

    def test_reuse_exact_only(self):
        self.assertEqual(resolve_strategy(**self.base)[0], 'reuse_exact')

    def test_name_does_not_cause_reuse(self):
        diff = semantic_diff(self.obs, {'customer_vlan': 300, 'tagging': 'tagged'})
        self.assertEqual(resolve_strategy(**{**self.base, 'diff': diff})[0], 'blocked')

    def test_block_other_tenant(self):
        self.assertEqual(resolve_strategy(**{**self.base, 'current_tenant': 'isp-b'})[1], 'cross_tenant_or_target')

    def test_block_other_olt(self):
        self.assertEqual(resolve_strategy(**{**self.base, 'current_olt': 'olt-2'})[0], 'blocked')

    def test_block_stale(self):
        self.assertEqual(resolve_strategy(**{**self.base, 'observation': replace(self.obs, freshness='stale')})[1], 'stale_or_unknown_snapshot')

    def test_block_fingerprint_drift(self):
        self.assertEqual(resolve_strategy(**{**self.base, 'source_fingerprint': 'other_hash'})[1], 'source_changed')

    def test_block_firmware_drift(self):
        self.assertEqual(resolve_strategy(**{**self.base, 'current_firmware': 'R021'})[1], 'target_drift')

    def test_block_card_drift(self):
        self.assertEqual(resolve_strategy(**{**self.base, 'current_card': 'XGS-PON'})[1], 'target_drift')

    def test_unknown_not_equal(self):
        obs = replace(self.obs, unknown_fields=frozenset({'gems'}))
        diff = semantic_diff(obs, {**self.obs.observed_settings, 'gems': [1]})
        self.assertEqual(diff['gems'], 'not_observable')
        self.assertEqual(resolve_strategy(**{**self.base, 'observation': obs, 'diff': diff})[0], 'blocked')

    def test_missing_key_diff(self):
        diff = semantic_diff(self.obs, {'customer_vlan': 200, 'service_vlan': 200})
        self.assertEqual(diff['service_vlan'], 'add')
        self.assertEqual(diff['tagging'], 'remove')

    def test_no_in_place_even_zero_refs(self):
        self.assertFalse(in_place_allowed(replace(self.obs, reference_count=0)))
        self.assertFalse(in_place_allowed(replace(self.obs, reference_count=None)))

    def test_clone_draft_is_not_deploy(self):
        status, why = resolve_strategy(**{**self.base, 'requested': 'clone_new_revision'})
        self.assertEqual((status, why), ('clone_new_revision', 'draft_only_requires_approval_to_deploy'))

    def test_separate_migration(self):
        status, why = resolve_strategy(**{**self.base, 'requested': 'plan_migration'})
        self.assertEqual(status, 'plan_migration')
        self.assertIn('separate_approval', why)

    def test_unknown_reference_blocks_migration(self):
        result = resolve_strategy(**{**self.base, 'requested': 'plan_migration', 'observation': replace(self.obs, reference_count=None)})
        self.assertEqual(result[1], 'references_unknown')

    def test_adopt_only_when_equal(self):
        self.assertEqual(resolve_strategy(**{**self.base, 'requested': 'adopt_reference'})[0], 'adopt_reference')

    def test_no_raw_cli(self):
        self.assertEqual(validate_edit({'raw_cli': 'sample'}, {'raw_cli'})[1], 'raw_or_secret_field_blocked')
        self.assertEqual(validate_edit({'commands': []}, {'commands'})[1], 'raw_or_secret_field_blocked')

    def test_vendor_field_not_allowlisted(self):
        self.assertEqual(validate_edit({'unknown_param': 1}, {'unknown_param'})[1], 'unknown_field_blocked')

    def test_field_not_supported(self):
        self.assertEqual(validate_edit({'customer_vlan': 200}, {'tagging'})[1], 'driver_capability_unsupported')

    def test_vlan_range(self):
        self.assertEqual(validate_edit({'customer_vlan': 4095}, {'customer_vlan'})[1], 'invalid_vlan')
        self.assertEqual(validate_edit({'customer_vlan': True}, {'customer_vlan'})[1], 'invalid_vlan')

    def test_qos_limits(self):
        self.assertEqual(validate_edit({'assured_kbps': 1000, 'maximum_kbps': 100}, {'assured_kbps', 'maximum_kbps'})[1], 'qos_min_exceeds_max')
        self.assertTrue(validate_edit({'assured_kbps': 100, 'maximum_kbps': 1000}, {'assured_kbps', 'maximum_kbps'})[0])

    def test_unknown_read_certification(self):
        self.assertEqual(resolve_strategy(**{**self.base, 'certified_read': False})[0], 'blocked')


if __name__ == '__main__':
    unittest.main()
