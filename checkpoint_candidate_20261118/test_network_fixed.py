import copy,json,time,unittest
from pathlib import Path
import subprocess,sys
DATA=Path(__file__).parent/"network_test/fixed_synthetic.json"
def check(b,items):
 r=subprocess.run([sys.executable,str(Path(__file__).parent/"network_validate.py"),json.dumps({"op":"prepare","head":"a"*40,"state":b,"items":items})],capture_output=True,text=True)
 if r.returncode:raise ValueError(r.stderr)
 return json.loads(r.stdout)
from checkpoint import prepare,digest
class NetworkFixed(unittest.TestCase):
 def setUp(self):self.d=json.loads(DATA.read_text())
 def test_fixed_scope_schema_accept(self):check(self.d['before'],self.d['items'])
 def test_missing_view_refused(self):
  items=copy.deepcopy(self.d['items']);items[0]['payload']['after']['events']=[];items[0]['sha256']=digest(items[0]['payload'])
  with self.assertRaises(Exception):check(self.d['before'],items)
 def test_bad_schema_refused(self):
  items=copy.deepcopy(self.d['items']);items[0]['payload']['after']['rows']['images'][0]['attributes']['content_kind'].update(status='observed',value='invalid',evidence='synthetic');items[0]['sha256']=digest(items[0]['payload'])
  with self.assertRaises(Exception):check(self.d['before'],items)
 def test_changed_identity_refused(self):
  b=copy.deepcopy(self.d['before']);b['koyo_index_handoffs'][self.d['key']]['destination']['model_id']='different'
  with self.assertRaises(Exception):check(b,self.d['items'])
