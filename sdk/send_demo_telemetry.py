import argparse, uuid
from darial_sdk import DarialClient
p=argparse.ArgumentParser(); p.add_argument('--api-key',required=True); p.add_argument('--product-id',required=True); p.add_argument('--agent-name',default='Legal Contract Agent'); p.add_argument('--base-url',default='http://localhost:8000'); a=p.parse_args()
c=DarialClient(a.base_url,a.api_key); t=f"real-demo-{uuid.uuid4()}"
print(c.track_run(event_id=t+'-run',product_id=a.product_id,agent_name=a.agent_name,trace_id=t,payload={'workflow_name':'contract_review','environment':'prod','status':'completed','latency_ms':7600,'total_cost':1.84}))
print(c.track_llm_call(event_id=t+'-llm',trace_id=t,model_name='qwen-72b-demo',provider='internal',input_tokens=4200,output_tokens=630,estimated_cost=1.71,latency_ms=6100))
print(c.track_tool_call(event_id=t+'-tool',trace_id=t,tool_name='document_search',latency_ms=850,estimated_cost=.13))
print(c.track_outcome(event_id=t+'-outcome',trace_id=t,outcome_type='contract_review_completed',success=True,quality_score=.94))
print('Создан trace:',t)
