import hashlib, json, tempfile, unittest, zipfile
from pathlib import Path
from pipeline_production.common import canonical, digest
from pipeline_production.small_transfer import export_images, fetch_posts

class TransferTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.root=Path(self.temp.name)
  self.data=[b'image-one',b'image-two']; self.hashes=[hashlib.sha256(x).hexdigest() for x in self.data]
  def post(n, hs): return {'post_id':str(n),'images':[{'path':'images/'+h+'.jpg','sha256':h} for h in hs]}
  self.m={'job_id':'prod-test','split':'production','dataset_version':'test','posts':[post(1,[self.hashes[0]]),post(2,self.hashes),post(3,[self.hashes[1]])]}
  self.bundle=self.root/'input.zip'
  with zipfile.ZipFile(self.bundle,'w') as z:
   z.writestr('manifest.json',canonical(self.m))
   for h,d in zip(self.hashes,self.data): z.writestr('images/'+h+'.jpg',d)
  self.source={'job_id':'prod-test','sha256':digest(self.bundle),'bytes':self.bundle.stat().st_size,'manifest_sha256':hashlib.sha256(canonical(self.m)).hexdigest(),'post_ids':['1','2','3']}
  self.policy={'post_ids':[],'image_sha256':[]}; self.export=self.root/'export'
  self.pin=export_images(self.bundle,self.source,self.policy,self.export)['index_sha256']; self.index=(self.export/'index.json').read_bytes(); self.calls=[]
 def fetch(self,path,limit):
  self.calls.append(path); data=(self.export/path).read_bytes(); self.assertLessEqual(len(data),limit); return data
 def runfetch(self, fetch=None, **kw):
  return fetch_posts(fetch or self.fetch,self.index,kw.get('pin',self.pin),self.source,self.policy,['1'],self.root/'out')
 def test_shared_hash_closure_and_individual_fetch(self):
  self.assertEqual([p['post_id'] for p in self.runfetch()],['1','2','3']); self.assertEqual(len(self.calls),3)
 def test_resume_reuses_images(self):
  self.runfetch(); self.calls=[]; self.runfetch(); self.assertEqual(self.calls,['manifest.json'])
 def test_deny_propagates_no_fallback(self):
  def denied(path,limit):
   if path.startswith('images/'): raise PermissionError('403')
   return self.fetch(path,limit)
  with self.assertRaises(PermissionError): self.runfetch(denied)
  self.assertFalse((self.root/'out/selection-receipt.json').exists())
 def test_tamper_rejected(self):
  def bad(path,limit): return b'bad' if path.startswith('images/') else self.fetch(path,limit)
  with self.assertRaises(ValueError): self.runfetch(bad)
 def test_bad_pin(self):
  with self.assertRaises(ValueError): self.runfetch(pin='0'*64)
 def test_export_overwrite_refused(self):
  with self.assertRaises(ValueError): export_images(self.bundle,self.source,self.policy,self.export)
 def test_exclusion_before_export(self):
  with self.assertRaises(ValueError): export_images(self.bundle,self.source,{'post_ids':['2'],'image_sha256':[]},self.root/'excluded')
  self.assertFalse((self.root/'excluded').exists())
 def test_partial_resume(self):
  count=0
  def interrupted(path,limit):
   nonlocal count
   if path.startswith('images/'):
    count+=1
    if count==2: raise OSError('interrupted')
   return self.fetch(path,limit)
  with self.assertRaises(OSError): self.runfetch(interrupted)
  self.calls=[]; self.runfetch(); self.assertEqual(len(self.calls),2)

if __name__=='__main__': unittest.main()
