#!/usr/bin/env python3
"""Explicit BYOK prompt runner; never enabled by the readiness scanner."""
import argparse,datetime,hashlib,http.client,json,os,ssl,time
ENGINES={'openai':('api.openai.com','/v1/chat/completions','OPENAI_API_KEY','gpt-4o-mini')}
def parse_response(d):
 answer=d['choices'][0]['message']['content']
 if not isinstance(answer,str) or not answer:raise ValueError('Missing engine answer')
 citations=d.get('citations',[])
 if not isinstance(citations,list) or any(not isinstance(x,str) or not x.startswith(('https://','http://')) for x in citations):raise ValueError('Invalid returned citations')
 return answer,citations

def run(engine,prompts,out):
 host,path,keyname,model=ENGINES[engine];key=os.environ.get(keyname,'')
 if not key:raise ValueError('Set '+keyname+' in your environment, not the prompt file')
 if not 1<=len(prompts)<=3 or any(not isinstance(p,str) or not 1<=len(p)<=600 for p in prompts):raise ValueError('Use 1-3 prompts, each at most 600 characters')
 with open(out,'x',encoding='utf-8') as f:
  for prompt in prompts:
   c=http.client.HTTPSConnection(host,timeout=60,context=ssl.create_default_context())
   try:
    body=json.dumps({'model':model,'messages':[{'role':'user','content':prompt}],'max_tokens':400,'temperature':0})
    c.request('POST',path,body,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    r=c.getresponse();raw=r.read(1000001)
    if r.status!=200:raise RuntimeError('Engine HTTP '+str(r.status)+'; no automatic retry')
    if len(raw)>1000000:raise ValueError('Engine response too large')
    d=json.loads(raw);answer,citations=parse_response(d)
    row={'engine':engine,'model':model,'prompt':prompt,'answer':answer,'citations':citations,'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'usage':d.get('usage',{}),'source_response_sha256':hashlib.sha256(raw).hexdigest(),'web_search':'provider-defined; plain OpenAI chat is not live ChatGPT search'}
    f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush()
   finally:c.close()
   time.sleep(1)

def main():
 p=argparse.ArgumentParser();p.add_argument('--engine',choices=ENGINES,required=True);p.add_argument('--prompts',required=True);p.add_argument('--out',default='answers.jsonl');p.add_argument('--accept-provider-charges',action='store_true');a=p.parse_args()
 if not a.accept_provider_charges:p.error('BYOK engine calls may cost money. Explicit --accept-provider-charges is required. No calls made.')
 with open(a.prompts,encoding='utf-8') as f:prompts=json.load(f)
 run(a.engine,prompts,a.out)
if __name__=='__main__':main()
