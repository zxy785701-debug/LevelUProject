"""Persisted retrieval checkpoints and shared actual-call hooks for every new flow."""
import asyncio
import hashlib
import json
from ..errors import AppError
from ..quiz_grounding.snapshots import EvidenceSegment
from .budgets import JobBudgets
from .embeddings import BailianEmbeddings
from .evidence import evidence_from_hit
from .retrieval import KnowledgeAgent,KnowledgeOutcome


class KnowledgeRetriever(JobBudgets):
    def __init__(self, accounts, config, index, *, embedding_factory=None,model=None,plan_gateway=None,public_plan=None,tools=None):
        super().__init__(accounts,config)
        self.index,self.model,self.plan_gateway,self.public_plan,self.tools = index,model,plan_gateway,public_plan,tools
        self.embedding_factory = embedding_factory or (lambda claim:BailianEmbeddings(accounts,config,claim))

    async def retrieve(self, claim, goal, documents, *, allow_web=True,total_model_limit=7,reserve=2):
        self.validate_documents(claim.user_id,documents)
        signature = hashlib.sha256(json.dumps([goal,allow_web,self.profile,
            [(d['id'],d['revision_id']) for d in documents]],ensure_ascii=False).encode()).hexdigest()
        checkpoint = await asyncio.to_thread(self.read_checkpoint,claim,'retrieval')
        if checkpoint:
            if checkpoint.get('signature') != signature:
                raise AppError('KNOWLEDGE_SCOPE_CHANGED','目标、资料或联网权限变化，请重新准备',409)
            return KnowledgeOutcome(evidence=[EvidenceSegment.model_validate(s) for s in checkpoint['segments']],
                trace=checkpoint['trace'],model_calls=checkpoint['model_calls'],tool_calls=checkpoint['tool_calls'],
                page_attempts=checkpoint['page_attempts'],reason_code=checkpoint['reason_code'],
                depends_on_documents=checkpoint['depends_on_documents'],knowledge_error=checkpoint['knowledge_error'])
        async def search(query,maximum):
            try:
                vector = await self.embedding_factory(claim).aembed_query(query)
                hits = await asyncio.to_thread(self.index.search,claim,documents,vector,maximum=maximum)
                return [evidence_from_hit(hit) for hit in hits]
            except AppError: raise
            except Exception:
                raise AppError('KNOWLEDGE_INDEX_UNAVAILABLE','知识库索引暂时无法读取，请重建后重试',503) from None
        async def before_model():
            await self.wait_model_call(claim,total_model_limit,phase='retrieval',reserve=reserve)
        async def before_tool(name,pages):
            await asyncio.to_thread(self.consume,claim,'tool_calls',1,self.accounts.settings.retrieval_tool_call_limit)
        async def before_pages(count):
            await asyncio.to_thread(self.consume,claim,'page_attempts',count,self.accounts.settings.retrieval_max_page_attempts)
        async def stage(value): await asyncio.to_thread(self.advance,claim,'retrieving',40)
        with self.database.session() as session:
            row = self._active(session,claim)
            user = self.accounts._user(session,row.user_id)
            protected = [user.id,user.openid,*[d['source']['filename'] for d in documents if d.get('source',{}).get('filename')]]
        agent = KnowledgeAgent(self.accounts.settings,knowledge_search=search,model=self.model,plan_gateway=self.plan_gateway,
            public_plan=self.public_plan,private_terms=protected,tools=self.tools,
            before_model=before_model,before_tool=before_tool,before_pages=before_pages,stage=stage)
        outcome = await agent.run(goal,allow_web=allow_web)
        content = {'signature':signature,'segments':[s.model_dump(mode='json') for s in outcome.evidence],'trace':outcome.trace,
            'model_calls':outcome.model_calls,'tool_calls':outcome.tool_calls,'page_attempts':outcome.page_attempts,
            'reason_code':outcome.reason_code,'depends_on_documents':outcome.depends_on_documents,'knowledge_error':outcome.knowledge_error}
        await asyncio.to_thread(self.checkpoint,claim,'retrieval',content,stage='retrieved',progress=50)
        return outcome
