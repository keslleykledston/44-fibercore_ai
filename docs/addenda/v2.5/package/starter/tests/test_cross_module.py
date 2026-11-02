import unittest
from starter.profile_matcher import Snapshot, match
from starter.expert_policy import ProfileObservation, in_place_allowed
from olt_provisioning.policy import choose_profile_binding

class IntegratedProfileStudioTest(unittest.TestCase):
    def setUp(self):
        self.snap = Snapshot('isp-a','olt-a','R015','GPON-16',True,True,'DBA-100',20,
                             {'customer_vlan':200,'tagging':'tagged'})
        self.args = dict(tenant='isp-a',olt='olt-a',firmware='R015',card='GPON-16',driver_read_certified=True)
    def test_exact_reuse(self):
        self.assertEqual(match(self.snap.settings,self.snap,**self.args)[0],'reuse_exact')
    def test_name_equal_different_content_must_clone(self):
        desired={'customer_vlan':201,'tagging':'tagged'}
        self.assertEqual(match(desired,self.snap,**self.args)[0],'clone_new_revision')
        self.assertEqual(choose_profile_binding('hash-a','DBA-100','hash-b',55),'conflict')
    def test_cross_tenant(self):
        self.assertEqual(match(self.snap.settings,self.snap,**{**self.args,'tenant':'isp-b'})[0],'blocked')
    def test_cross_olt(self):
        self.assertEqual(match(self.snap.settings,self.snap,**{**self.args,'olt':'olt-b'})[0],'blocked')
    def test_firmware_drift(self):
        self.assertEqual(match(self.snap.settings,self.snap,**{**self.args,'firmware':'R021'})[0],'blocked')
    def test_unknown_blocks(self):
        from dataclasses import replace
        snap=replace(self.snap,unknown_fields=frozenset({'gems'}))
        self.assertEqual(match(self.snap.settings,snap,**self.args)[0],'blocked')
    def test_stale_blocks(self):
        from dataclasses import replace
        snap=replace(self.snap,fresh=False)
        self.assertEqual(match(self.snap.settings,snap,**self.args)[0],'blocked')
    def test_uncertified_read_blocks(self):
        self.assertEqual(match(self.snap.settings,self.snap,**{**self.args,'driver_read_certified':False})[0],'blocked')
    def test_never_mutate_in_place(self):
        observation=ProfileObservation('isp-a','olt-a','R015','GPON-16','fresh','hash',0,{})
        self.assertFalse(in_place_allowed(observation))
