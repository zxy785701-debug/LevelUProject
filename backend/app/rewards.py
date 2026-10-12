"""A quiz keeps its reward rate so historical totals never change."""


def question_reward(quiz: dict) -> dict:
    return quiz.get('reward') or {'xp': 10, 'coins': 2}


def new_quiz_reward(difficulty: str) -> dict:
    return {'xp': 15, 'coins': 3} if difficulty == 'medium' else {'xp': 10, 'coins': 2}
