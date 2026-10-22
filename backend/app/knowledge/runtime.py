"""Resources owned solely by the live, locked executor process."""
from ..errors import AppError
from .index import VectorIndex
from .indexing import ImportIndexer
from .cleanup import CleanupManager
from .question_pipeline import QuestionPipeline
from .scopes import ScopePipeline
from .quizzes import QuizPipeline


class WorkerRuntime:
    def __init__(self, accounts, config, *, lock, guard):
        self.accounts,self.config = accounts,config
        self.index = VectorIndex(accounts,config,lock=lock,guard=guard)
        self.imports = ImportIndexer(accounts,config,self.index)
        self.cleaner = CleanupManager(accounts,config,self.index)
        self.questions = QuestionPipeline(accounts,config,self.index)
        self.scopes = ScopePipeline(accounts,config,self.index)
        self.quizzes = QuizPipeline(accounts,config,self.index)
        self.closed = False

    def process(self, claim):
        reason = self.config.model_copy(update={'enabled':True}).unavailable_reason()
        if reason: raise AppError(reason,'知识库处理配置未就绪，请检查独立向量配置后重试',503)
        if claim.kind in ('import','reindex'): return self.imports.process(claim)
        if claim.kind == 'question': return self.questions.process(claim)
        if claim.kind == 'prepare': return self.scopes.process(claim)
        if claim.kind == 'quiz': return self.quizzes.process(claim)
        raise AppError('KNOWLEDGE_JOB_UNSUPPORTED','执行器不支持此任务类型，请更新后重试',503)

    def cleanup(self):
        self.cleaner.collect_garbage()
        return self.cleaner.process_one()

    def close(self):
        if not self.closed:
            self.index.close()
            self.closed = True
