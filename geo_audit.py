#!/usr/bin/env python3
"""Public technical-readiness scanner. No model calls, keys or tracking."""
import argparse,csv,datetime,hashlib,http.client,ipaddress,json,re,socket,ssl
from urllib.parse import urlsplit
from vendor import orangeo
MAX_BYTES=2000000

def public_addresses(host):
 addresses=sorted({r[4][0] for r in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)})
 if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):raise ValueError('Host must resolve only to public addresses')
 return addresses

def fetch(url):
 p=urlsplit(url)
 if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):raise ValueError('Only public HTTPS URLs without credentials are allowed')
 host=p.hostname;address=public_addresses(host)[0]
 class PinnedHTTPS(http.client.HTTPSConnection):
  def connect(self):
   raw=socket.create_connection((address,443),timeout=60)
   self.sock=ssl.create_default_context().wrap_socket(raw,server_hostname=host)
 c=PinnedHTTPS(host,timeout=60)
 try:
  path=p.path or '/'
  if p.query:path+='?'+p.query
  c.request('GET',path,headers={'Host':host,'User-Agent':'PillarGEOReadiness/1.0','Accept-Encoding':'identity'})
  r=c.getresponse();data=r.read(MAX_BYTES+1)
  if len(data)>MAX_BYTES:raise ValueError('Response exceeds 2 MB')
  if 300<=r.status<400:raise ValueError('Redirect refused; enter its verified final HTTPS URL')
  return r.status,data
 finally:c.close()

def audit(url,brand,category):
 p=urlsplit(url)
 if p.path not in ('','/') or p.query or p.fragment:raise ValueError('Enter the site origin, without path/query/fragment')
 origin=url.rstrip('/');pages={};evidence=[]
 for path in ['/','/robots.txt','/llms.txt','/sitemap.xml']:
  u=origin+path;status,data=fetch(u);pages[path]=(status,data.decode('utf-8','replace'));evidence.append({'url':u,'status':status,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
 if pages['/'][0]!=200:raise ValueError('Homepage did not return HTTP 200')
 sig=orangeo.parse_page(pages['/'][1]);return {'kind':'technical_readiness','observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'site':origin,'brand':brand,'evidence':evidence,'signals':{'title':sig.title,'description':sig.description,'h1s':sig.h1s,'canonical':sig.canonical,'schema_types':sig.schema_types},'robots':orangeo.analyze_robots(pages['/robots.txt'][1] if pages['/robots.txt'][0]==200 else '', '/'),'llms':orangeo.analyze_llms(pages['/llms.txt'][1],pages['/llms.txt'][0],brand,category),'sitemap':orangeo.analyze_sitemap(pages['/sitemap.xml'][1],pages['/sitemap.xml'][0]),'buyer_prompts':orangeo.generate_prompts(brand,category,[],'Ghana / English'),'measurement':'Content and crawl-policy signals. Answer-engine mentions and citations are separate measurements.'}

def score_responses(path,brand):
 """Score exact saved engine responses, never invented citations."""
 rows=[]
 with open(path,encoding='utf-8') as response_file:
  lines=response_file.readlines()
 for line in lines:
  if not line.strip():continue
  d=json.loads(line)
  if not all(isinstance(d.get(k),str) and d[k] for k in ('engine','prompt','answer','observed_at')):raise ValueError('Each response needs engine, prompt, answer, observed_at')
  citations=d.get('citations',[])
  if not isinstance(citations,list) or any(not isinstance(u,str) or urlsplit(u).scheme not in ('http','https') for u in citations):raise ValueError('Citations must be observed HTTP(S) URL strings')
  mention=bool(re.search(r'(?<!\w)'+re.escape(brand)+r'(?!\w)',d['answer'],re.I))
  rows.append({'engine':d['engine'],'prompt':d['prompt'],'observed_at':d['observed_at'],'brand_mentioned':mention,'citation_urls':citations,'response_sha256':hashlib.sha256(d['answer'].encode()).hexdigest()})
 return {'brand':brand,'responses':rows,'response_count':len(rows),'mention_count':sum(r['brand_mentioned'] for r in rows),'measurement':'String mention counts in supplied responses, not rankings or guaranteed visibility.'}

def main():
 p=argparse.ArgumentParser();p.add_argument('--url');p.add_argument('--brand',required=True);p.add_argument('--category',default='software');p.add_argument('--responses');p.add_argument('--out',default='report.json');p.add_argument('--csv',default='evidence.csv');a=p.parse_args()
 if not a.url and not a.responses:p.error('Use --url or --responses')
 result=score_responses(a.responses,a.brand) if a.responses else audit(a.url,a.brand,a.category)
 with open(a.out,'w',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
 rows=result.get('responses',result.get('evidence',[]))
 if rows:
  with open(a.csv,'w',newline='',encoding='utf-8') as f:
   w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 print(a.out);print(a.csv)
if __name__=='__main__':main()
