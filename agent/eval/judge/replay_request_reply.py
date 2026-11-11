"""Replay the draft-acceptance step on a run: which templates/rule replies would be replaced, old code vs new."""
import json,glob,sys,importlib.util,asyncio
sys.path.insert(0,'.')
from agent.harness import agent, rule_requests as R
spec=importlib.util.spec_from_file_location('agent.harness.agent_old',sys.argv[3]); old=importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
from agent.harness.citation_repair import repair_citations
U={}
for f in glob.glob(sys.argv[2]):
    for l in open(f): r=json.loads(l); U[r['key']]=r
V={}
for f in glob.glob(sys.argv[2].replace('turns_','verdicts_')):
    for l in open(f):
        if l.strip(): r=json.loads(l); V[r['key']]=r['verdict']
rows=[json.loads(l) for l in open(sys.argv[1])]
verbose=len(sys.argv)>4
def kinds(t):
    msgs=t['previous_user_messages'][-6:]; k=R.classify(t['user']); ck=next((R.classify(m) for m in reversed(msgs) if R.classify(m)),None)
    return k,ck
O={};N={}
for r in rows:
    for rec in r['records']:
        a=rec.get('answer') or ''; k=r['id']+'#'+str(rec['turn']); t=U.get(k)
        if not t or agent._ASKS_QUESTION_RE.search(t['user']): continue
        st=next((s for s in (rec.get('trace') or []) if s.get('stage')=='initial'),{}); ini=st.get('preview') or ''
        ini,_=repair_citations(ini,[]); fc=st.get('violations')==['evidence_not_support_query']
        ut="\n".join(t['previous_user_messages'][-4:]+[t['user']]); rk,ck=kinds(t)
        if 'prompt_leak' in (rk,ck): continue
        if a==old.NOT_A_QUESTION_REPLY or old._looks_like_refusal(a) or a==old._REASONLESS_RULE_REPLY:
            e=old._explained_refusal(ini,ut,facts_checked=fc)
            if e: O[k]=e
        if a==agent.NOT_A_QUESTION_REPLY or agent._looks_like_refusal(a) or a in agent._REPLACEABLE_RULE_REPLIES:
            strict=agent._needs_refusal_first(t["user"],rk,ck)
            e=agent._request_reply(ini,ut,strict=strict,facts_checked=fc)
            if e: N[k]=(strict,t['expected_behavior'],t['user'][:90],e,V.get(k))
print('old kept',len(O),'new kept',len(N),'lost',sorted(set(O)-set(N)))
for k in sorted(set(N)-set(O)):
    x=N[k]; print('==',k,'strict' if x[0] else 'LOOSE',x[1],'was',x[4],'|',x[2].replace('\n',' ')); print('   ',x[3][:(700 if verbose else 330)].replace('\n',' / '))
