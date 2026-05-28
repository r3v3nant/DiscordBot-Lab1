import discord
import yaml
import os
from dotenv import load_dotenv
import time
import asyncio
from discord import app_commands
from discord.ext import commands
import db_manager
from models import ItemCollection, Engine

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

class BotManager(commands.Bot):
    """Головний диригент бота"""

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="/", intents=intents)
        self.active_sessions = {}  # user_id -> {'engine': Engine, 'test_id': int, 'task': Task}

    async def setup_hook(self):
        db_manager.init_db()
        await self.tree.sync()


bot = BotManager()


# --- Discord UI Компоненти (Кнопки) ---

class MainMenuView(discord.ui.View):
    """Кнопки головного меню при старті"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Choose test", style=discord.ButtonStyle.success, custom_id="menu_choose_test")
    async def choose_test_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in bot.active_sessions:
            await interaction.response.send_message("Ви вже проходите тест! Завершіть його.", ephemeral=True)
            return

        view = TestSelectionView()
        await interaction.response.send_message("Оберіть доступний тест зі списку нижче:", view=view, ephemeral=True)

    @discord.ui.button(label="My results", style=discord.ButtonStyle.secondary, custom_id="menu_results")
    async def results_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_results = db_manager.get_user_results(str(interaction.user.id))
        if not user_results:
            await interaction.response.send_message("У вас ще немає збережених результатів.", ephemeral=True)
            return

        msg = "**Ваша історія тестувань:**\n"
        for test_name, score, date in user_results:
            msg += f"• *{test_name}* — **{score}%** ({date})\n"
        await interaction.response.send_message(msg, ephemeral=True)

class TestSelectionView(discord.ui.View):
    """Кнопки вибору доступних тестів"""

    def __init__(self):
        super().__init__(timeout=60)
        for filename in os.listdir("data"):
            if filename.endswith(".yaml"):
                test_slug = filename.replace(".yaml", "")
                self.add_item(
                    discord.ui.Button(label=test_slug.replace("_", " ").title(), custom_id=f"start_test_{filename}"))


class QuizInterfaceView(discord.ui.View):
    """Кнопки варіантів відповідей для кожного питання"""

    def __init__(self, engine: Engine, user_id: int):
        super().__init__(timeout=None)
        self.engine = engine
        self.user_id = user_id
        question = engine.get_current_question()

        for option in question.options:
            button = discord.ui.Button(label=option, style=discord.ButtonStyle.blurple)
            button.callback = self.make_callback(option)
            self.add_item(button)

    def make_callback(self, chosen_option: str):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("Це не ваш тест!", ephemeral=True)
                return

            # Перевірка відповіді та перехід далі
            self.engine.check_answer(chosen_option)
            self.engine.current_index += 1

            await next_question_or_finish(interaction, self.user_id)

        return callback


# --- Допоміжні функції логіки ---

async def next_question_or_finish(interaction: discord.Interaction, user_id: int):
    session = bot.active_sessions.get(user_id)
    if not session:
        return

    engine = session['engine']
    next_q = engine.get_current_question()

    if next_q:
        view = QuizInterfaceView(engine, user_id)
        embed = discord.Embed(title=f"Питання {engine.current_index + 1}", description=next_q.question, color=0x3498db)
        await interaction.response.edit_message(embed=embed, view=view)
    else:
        # Тест завершено успішно користувачем
        if session['task']:
            session['task'].cancel()  # Скасовуємо таймер таймауту
        await finish_test(interaction, user_id)


async def test_timeout_timer(user_id: int, duration: int, channel: discord.TextChannel):
    """Асинхронний таймер, який оновлює час кожні 10 секунд та завершує тест за таймаутом"""
    time_left = duration
    interval = 15  # Інтервал оновлення в секундах

    while time_left > 0:
        # Перевіряємо, чи тест не було завершено вручну користувачем
        if user_id not in bot.active_sessions:
            return  # Якщо сесії вже немає, просто виходимо з циклу

        session = bot.active_sessions[user_id]

        # Якщо ми вже встигли зберегти об'єкт повідомлення в сесію
        if 'message' in session and session['message']:
            try:
                mins, secs = divmod(time_left, 60)
                time_str = f"{mins:02d}:{secs:02d}"

                # Редагуємо повідомлення, зберігаючи поточний embed та view
                # Це оновлює лише рядок з часом над тестом
                await session['message'].edit(
                    content=f":alarm_clock: Залишилося часу: `{time_str}`"
                )
            except discord.NotFound:
                # Якщо користувач чомусь видалив повідомлення, зупиняємо таймер
                break
            except Exception as e:
                print(f"Помилка оновлення таймера: {e}")

        # Чекаємо 10 секунд (або менше, якщо залишилося мало часу)
        sleep_time = min(interval, time_left)
        await asyncio.sleep(sleep_time)
        time_left -= sleep_time

    # --- КОД ЗАВЕРШЕННЯ ЗА ТАЙМАУТОМ (якщо час вийшов) ---
    if user_id in bot.active_sessions:
        session = bot.active_sessions[user_id]
        engine = session['engine']
        db_manager.save_result(str(user_id), session['test_id'], engine.stats.percent)

        # Видаляємо сесію
        del bot.active_sessions[user_id]

        # Оновлюємо фінальне повідомлення (прибираємо кнопки)
        if 'message' in session and session['message']:
            try:
                embed_timeout = discord.Embed(
                    title=":alarm_clock: Час вичерпано!",
                    description=f"Ваш тест завершено автоматично.\nРезультат: **{engine.stats.percent}%**",
                    color=0xe74c3c
                )
                await session['message'].edit(content=f"<@{user_id}> Час вийшов!", embed=embed_timeout, view=None)
                return
            except Exception:
                pass

        # Резервний варіант, якщо повідомлення не вдалося відредагувати
        embed = discord.Embed(title=":alarm_clock: Час вичерпано!",
                              description=f"Ваш тест завершено автоматично.\nРезультат: **{engine.stats.percent}%**",
                              color=0xe74c3c)
        await channel.send(content=f"<@{user_id}>", embed=embed)


async def finish_test(interaction: discord.Interaction, user_id: int):
    session = bot.active_sessions.pop(user_id, None)
    if session:
        engine = session['engine']
        db_manager.save_result(str(user_id), session['test_id'], engine.stats.percent)

        # 1. Рахуємо витрачений час у секундах
        elapsed_seconds = int(time.time() - session['start_time'])

        # 2. Форматуємо час у хвилини та секунди для красивого виводу
        minutes = elapsed_seconds // 60
        seconds = elapsed_seconds % 60
        time_str = f"{minutes} хв. {seconds} сек." if minutes > 0 else f"{seconds} сек."

        score = engine.stats.percent
        if score < 50:
            embed_color = 0xe74c3c  # Червоний
            status_emoji = ":x:"
        elif score < 80:
            embed_color = 0xf1c40f  # Жовтий
            status_emoji = ":warning:"
        else:
            embed_color = 0x2ecc71  # Зелений
            status_emoji = ":tada:"

        # 3. Додаємо інформацію про час у Discord Embed
        embed = discord.Embed(
            title=f"{status_emoji} Тест завершено!",
            description=f"Вітаємо! Ви пройшли тест.\n\n"
                        f"• Правильних відповідей: **{engine.stats.correct}/{engine.stats.total}**\n"
                        f"• Ваш бал: **{score}%**\n"
                        f"• Час проходження: **{time_str}**",
            color=embed_color  # Передаємо обраний колір сюди
        )
        await interaction.response.edit_message(embed=embed, view=None)


# --- Slash Команди бота ---

@bot.tree.command(name="start", description="Початок роботи з ботом")
async def start(interaction: discord.Interaction):
    db_manager.save_user(str(interaction.user.id), interaction.user.name)
    view = MainMenuView()
    await interaction.response.send_message(
        f"Привіт, {interaction.user.mention}! Використовуйте команду/кнопку `/choose_test` для запуску тестування або `/results` для перегляду історії.",
        view=view,
        ephemeral=True)


@bot.tree.command(name="choose_test", description="Обрати тест для проходження")
async def choose_test(interaction: discord.Interaction):
    if interaction.user.id in bot.active_sessions:
        await interaction.response.send_message("Ви вже проходите тест! Завершіть його.", ephemeral=True)
        return

    view = TestSelectionView()
    await interaction.response.send_message("Оберіть доступний тест зі списку нижче:", view=view, ephemeral=True)


@bot.tree.command(name="results", description="Переглянути історію своїх результатів")
async def results(interaction: discord.Interaction):
    user_results = db_manager.get_user_results(str(interaction.user.id))
    if not user_results:
        await interaction.response.send_message("У вас ще немає збережених результатів.", ephemeral=True)
        return

    msg = "**Ваша історія тестувань:**\n"
    for test_name, score, date in user_results:
        msg += f"• *{test_name}* — **{score}%** ({date})\n"
    await interaction.response.send_message(msg, ephemeral=True)


# --- Обробник натискання на вибір тесту ---
@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.data and 'custom_id' in interaction.data:
        custom_id = interaction.data['custom_id']
        if custom_id.startswith("start_test_"):
            filename = custom_id.replace("start_test_", "")
            user_id = interaction.user.id

            with open(f"data/{filename}", "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            test_id = db_manager.save_test(data['test_name'], data['time_limit'])

            # Ініціалізація моделей
            collection = ItemCollection(data['questions'])
            #collection.shuffle_all()
            engine = Engine(collection)

            # Запуск асинхронного таймера обмеження часу
            timer_task = asyncio.create_task(test_timeout_timer(user_id, data['time_limit'], interaction.channel))
            bot.active_sessions[user_id] = {'engine': engine, 'test_id': test_id, 'task': timer_task}

            # Посилання на перше питання
            first_q = engine.get_current_question()
            view = QuizInterfaceView(engine, user_id)
            embed = discord.Embed(title=f"Тест: {data['test_name']}\nПитання 1", description=first_q.question,
                                  color=0x3498db)

            # Форматуємо початковий час для виведення
            mins, secs = divmod(data['time_limit'], 60)

            # 1. Редагуємо повідомлення
            await interaction.response.edit_message(
                content=f":alarm_clock: Залишилося часу: `{mins:02d}:{secs:02d}`",
                embed=embed,
                view=view
            )

            # 2. Отримуємо об'єкт цього повідомлення, щоб таймер міг його редагувати
            msg_obj = await interaction.original_response()

            # 3. Запуск асинхронного таймера
            timer_task = asyncio.create_task(test_timeout_timer(user_id, data['time_limit'], interaction.channel))

            # 4. Фіксуємо повні дані сесії, включаючи об'єкт повідомлення 'message'
            bot.active_sessions[user_id] = {
                'engine': engine,
                'test_id': test_id,
                'task': timer_task,
                'start_time': time.time(),
                'message': msg_obj  # Передаємо повідомлення для таймера
            }

bot.run(TOKEN)
