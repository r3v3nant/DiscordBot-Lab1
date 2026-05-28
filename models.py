import random


class Item:
    """Клас окремого питання"""

    def __init__(self, data: dict):
        self.id = data['id']
        self.question = data['question']
        self.options = data['options'].copy()
        # Зберігаємо текст правильної відповіді ДО перемішування
        self.correct_answer_text = data['options'][data['answer']]


class ItemCollection:
    """Колекція оригінальних питань (шаблон)"""

    def __init__(self, questions_list: list):
        # Просто створюємо список об'єктів питань у початковому вигляді
        self.questions = [Item(q) for q in questions_list]


class Statistics:
    """Підрахунок результатів"""

    def __init__(self, total_questions: int):
        self.total = total_questions
        self.correct = 0

    def add_correct(self):
        self.correct += 1

    @property
    def percent(self) -> float:
        return round((self.correct / self.total) * 100, 2) if self.total > 0 else 0.0


class Engine:
    """Логіка проведення поточного тесту (динамічна сесія)"""

    def __init__(self, collection: ItemCollection):
        # 1. Глибоке копіювання питань, щоб не міняти оригінальну колекцію
        self.run_questions = []
        for q in collection.questions:
            # Створюємо копію питання для цієї сесії
            copied_item = Item({
                'id': q.id,
                'question': q.question,
                'options': q.options.copy(),
                'answer': q.options.index(q.correct_answer_text)
            })
            # 2. Перемішуємо варіанти відповідей САМЕ ДЛЯ ЦІЄЇ СЕСІЇ
            random.shuffle(copied_item.options)
            self.run_questions.append(copied_item)

        # 3. Перемішуємо порядок самих питань у тесті
        random.shuffle(self.run_questions)

        self.current_index = 0
        self.stats = Statistics(len(self.run_questions))

    def get_current_question(self) -> Item:
        if self.current_index < len(self.run_questions):
            return self.run_questions[self.current_index]
        return None

    def check_answer(self, chosen_text: str) -> bool:
        current_q = self.get_current_question()
        if current_q and chosen_text == current_q.correct_answer_text:
            self.stats.add_correct()
            return True
        return False
