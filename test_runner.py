import unittest
from unittest.mock import patch
import engine_runner as r
class Tests(unittest.TestCase):
 def test_parse(self):self.assertEqual(r.parse_response({'choices':[{'message':{'content':'fixture only'}}],'citations':['https://example.com/']}),('fixture only',['https://example.com/']))
 def test_missing_citations(self):self.assertEqual(r.parse_response({'choices':[{'message':{'content':'fixture only'}}]})[1],[])
 def test_invalid_citations(self):
  with self.assertRaises(ValueError):r.parse_response({'choices':[{'message':{'content':'fixture'}}],'citations':['file:///secret']})
 def test_no_key(self):
  with patch.dict('os.environ',{},clear=True):
   with self.assertRaises(ValueError):r.run('openai',['test'],'unused.jsonl')
if __name__=='__main__':unittest.main()
