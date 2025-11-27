# assessment/tasks.py
from celery import shared_task
# from .services import llm_evaluate_open_answer, llm_generate_recommendations
from .models import TestAnswer, TestSession

# @shared_task
# def evaluate_open_answer_task(answer_id):
#     ans = TestAnswer.objects.get(id=answer_id)
#     res = llm_evaluate_open_answer(ans.answer_text, ans.question.question_json)
#     ans.score = res.get("score")
#     ans.ai_feedback = {"errors": res.get("errors"), "correction": res.get("correction")}
#     ans.save()
#
# @shared_task
# def generate_recommendations_task(session_id):
#     session = TestSession.objects.get(id=session_id)
#     protocol = finalize_session(session)  # or call services.finalize_session
#     llm_res = llm_generate_recommendations(protocol)
#     protocol["llm"] = llm_res
#     session.protocol_json = protocol
#     session.save()
