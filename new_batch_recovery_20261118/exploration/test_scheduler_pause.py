import unittest
from protocol_bridge import ReviewedClockGuard
from exploration import Refused
class Pause(unittest.TestCase):
 def test_paused_plan_rejected_before_exploration_or_clock_write(self):
  guard=ReviewedClockGuard('/unused',{'payload':{}})
  state={'koyo_retained_work':{'key':{}},'koyo_index_handoffs':{'key':{}}}
  with self.assertRaisesRegex(Refused,'retained paused'):
   guard('head',state,{'plan_sha256':'key'})
