from __future__ import annotations
import json, uuid
from dataclasses import dataclass, field
from typing import Any
from urllib import request

@dataclass
class DarialClient:
    base_url: str
    api_key: str
    timeout: int = 10
    _buffer: list[dict[str, Any]] = field(default_factory=list)
    def _post(self, path, payload):
        req = request.Request(f"{self.base_url.rstrip('/')}{path}", data=json.dumps(payload).encode(), method="POST", headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        with request.urlopen(req, timeout=self.timeout) as response: return json.loads(response.read().decode())
    def track_event(self, event_type, payload, *, event_id=None, product_id=None, agent_name=None, trace_id=None):
        return self._post("/api/ingestion/events", {"event_id": event_id or str(uuid.uuid4()), "event_type": event_type, "product_id": product_id, "agent_name": agent_name, "trace_id": trace_id, "payload": payload})
    def track_run(self, *, agent_name, trace_id, payload, event_id=None, product_id=None): return self.track_event("agent_run", payload, event_id=event_id, product_id=product_id, agent_name=agent_name, trace_id=trace_id)
    def track_llm_call(self, *, trace_id, model_name, provider, input_tokens, output_tokens, estimated_cost=0, latency_ms=None, event_id=None): return self.track_event("llm_call", {"model_name":model_name,"provider":provider,"input_tokens":input_tokens,"output_tokens":output_tokens,"estimated_cost":estimated_cost,"latency_ms":latency_ms}, event_id=event_id, trace_id=trace_id)
    def track_tool_call(self, *, trace_id, tool_name, status="completed", latency_ms=None, estimated_cost=0, event_id=None): return self.track_event("tool_call", {"tool_name":tool_name,"status":status,"latency_ms":latency_ms,"estimated_cost":estimated_cost}, event_id=event_id, trace_id=trace_id)
    def track_outcome(self, *, trace_id, outcome_type, success, quality_score=None, event_id=None): return self.track_event("business_outcome", {"outcome_type":outcome_type,"success":success,"quality_score":quality_score}, event_id=event_id, trace_id=trace_id)
