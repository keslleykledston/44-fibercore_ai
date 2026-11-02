import unittest
from olt_provisioning.policy import Target, Certification, eligibility, choose_profile_binding

class TestPlanGuards(unittest.TestCase):
    def setUp(self):
        self.t = Target('t1','olt-01','0/1/3','SN123','R015-verified','GPON-16PON-verified')
        self.c = Certification('huawei','R015-verified','GPON-16PON-verified',True)
        self.k = dict(observed_tenant='t1',observed_fresh=True,matching_order=True,conflict=False,approval=True)
    def test_valid_lab_case(self):
        self.assertTrue(eligibility(self.t,self.c,**self.k)[0])
    def test_cross_tenant(self):
        self.assertEqual(eligibility(self.t,self.c,**{**self.k,'observed_tenant':'t2'})[1], 'cross_tenant')
    def test_stale(self):
        self.assertEqual(eligibility(self.t,self.c,**{**self.k,'observed_fresh':False})[1], 'stale_observation')
    def test_conflict(self):
        self.assertEqual(eligibility(self.t,self.c,**{**self.k,'conflict':True})[1], 'conflict')
    def test_order_not_verified(self):
        self.assertEqual(eligibility(self.t,self.c,**{**self.k,'matching_order':False})[1], 'association_unverified')
    def test_driver_uncertified(self):
        self.assertEqual(eligibility(self.t,Certification('huawei',self.t.firmware,self.t.card,False),**self.k)[1], 'write_not_certified')
    def test_wrong_card(self):
        self.assertEqual(eligibility(self.t,Certification('huawei',self.t.firmware,'wrong',True),**self.k)[1], 'driver_version_not_certified')
    def test_not_approved(self):
        self.assertEqual(eligibility(self.t,self.c,**{**self.k,'approval':False})[1], 'approval_missing')
    def test_profile_reuse(self):
        self.assertEqual(choose_profile_binding('abc','FC-100','abc',27),'reuse')
    def test_profile_create(self):
        self.assertEqual(choose_profile_binding('abc',None,None,0),'create')
    def test_profile_conflict(self):
        self.assertEqual(choose_profile_binding('abc','FC-100','xyz',27),'conflict')
if __name__=='__main__': unittest.main()
