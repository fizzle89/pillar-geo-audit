import unittest,tempfile,json
from unittest.mock import patch
import geo_audit as g
class Tests(unittest.TestCase):
 def test_private_dns(self):
  with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
   with self.assertRaises(ValueError):g.public_addresses('test')
 def test_mixed_dns(self):
  with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('1.1.1.1',443)),(2,1,6,'',('10.0.0.1',443))]):
   with self.assertRaises(ValueError):g.public_addresses('test')
 def test_credentials(self):
  with self.assertRaises(ValueError):g.fetch('https://user:pw@example.com')
 def test_http(self):
  with self.assertRaises(ValueError):g.fetch('http://example.com')
 def test_port(self):
  with self.assertRaises(ValueError):g.fetch('https://example.com:8888')
 def test_origin_only(self):
  with self.assertRaises(ValueError):g.audit('https://example.com/path','test','test')
 def test_exact_mention(self):
  with tempfile.NamedTemporaryFile(mode='w+',suffix='.jsonl') as f:
   f.write(json.dumps({'engine':'fixture','prompt':'test','answer':'Pillar Fabric is named here.','observed_at':'fixture','citations':['https://example.com/']})+'\n');f.flush();r=g.score_responses(f.name,'Pillar Fabric');self.assertEqual(r['mention_count'],1);self.assertEqual(r['response_count'],1)
 def test_no_substring_mention(self):
  with tempfile.NamedTemporaryFile(mode='w+',suffix='.jsonl') as f:
   f.write(json.dumps({'engine':'fixture','prompt':'test','answer':'pillarfabricated','observed_at':'fixture'})+'\n');f.flush();self.assertEqual(g.score_responses(f.name,'pillar')['mention_count'],0)
if __name__=='__main__':unittest.main()
