import logging
import asyncio
import psycopg2 # Supabase bilan ishlash uchun yangi kutubxona
import random
import io
import os
from datetime import timedelta
from aiohttp import web

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from PIL import Image, ImageDraw

BOT_TOKEN = "8715023932:AAGPYpZ6VY6v_fGeuvN6Ru7KaC0GmBwGcUE" # O'zingizning tokeningiz
ADMIN_ID = 8496927148 

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Baza ulanishini osonlashtiruvchi funksiya
def get_db_conn():
    return psycopg2.connect(
        host="aws-1-eu-central-1.pooler.supabase.com",
        port="6543",                           # <--- 5432 o'rniga 6543
        database="postgres",
        user="postgres.wmefxgwpkdskcnbrwcjy",  # <--- ID aniq qo'shildi
        password="Alisher1101@#"               # <--- Oxiridagi bo'sh joy (probel) olib tashlandi
    )

def init_db():
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS tests (id SERIAL PRIMARY KEY, name TEXT UNIQUE, creator_id BIGINT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS questions (
            id SERIAL PRIMARY KEY, test_id INTEGER, creator_id BIGINT,
            question_photo_id TEXT, correct_answer_photo_id TEXT,
            wrong1_photo_id TEXT, wrong2_photo_id TEXT, wrong3_photo_id TEXT,
            time_limit INTEGER DEFAULT 60
        )''')
    conn.commit()
    conn.close()

init_db()

class CreateQuiz(StatesGroup):
    GET_NEW_NAME = State()
    GET_RANGE = State()
    GET_Q = State()
    GET_A = State()
    GET_W1 = State()
    GET_W2 = State()
    GET_W3 = State()
    GET_TIME = State()

class SolveQuiz(StatesGroup):
    IN_PROGRESS = State()

async def merge_quiz_images(bot: Bot, q_id, a_id, w1_id, w2_id, w3_id):
    ids = [q_id, a_id, w1_id, w2_id, w3_id]
    images = []
    
    for file_id in ids:
        file = await bot.get_file(file_id)
        file_io = io.BytesIO()
        await bot.download_file(file.file_path, destination=file_io)
        file_io.seek(0)
        img = Image.open(file_io).convert("RGBA")
        images.append(img)

    max_width = max(img.width for img in images) + 20 
    total_height = sum(img.height for img in images) + len(images) * 20

    merged_img = Image.new("RGBA", (max_width, total_height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(merged_img)

    current_y = 10
    for i, img in enumerate(images):
        x_offset = (max_width - img.width) // 2
        merged_img.paste(img, (x_offset, current_y), img)
        current_y += img.height + 10
        
        if i < len(images) - 1:
            draw.line([(20, current_y), (max_width - 20, current_y)], fill=(200, 200, 200, 255), width=2)
            current_y += 10

    output_io = io.BytesIO()
    merged_img.save(output_io, format="PNG")
    output_io.seek(0)
    return BufferedInputFile(output_io.read(), filename="quiz.png")

@dp.message(Command("add"))
async def cmd_add(message: types.Message, state: FSMContext):
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="🆕 Yangi test yaratish", callback_data="add_new_test")
    builder.button(text="📚 Mavjud testga qism qo'shish", callback_data="add_exist_test")
    builder.adjust(1)
    await message.answer("🛠 Test yaratish bo'limi. Nima qilamiz?", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "add_new_test")
async def add_new_test(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("Yangi test uchun asosiy nomni yozing:\n(Masalan: Oliy Matematika)")
    await state.set_state(CreateQuiz.GET_NEW_NAME)

@dp.callback_query(F.data == "add_exist_test")
async def add_exist_test(call: types.CallbackQuery, state: FSMContext):
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM tests")
    tests = cursor.fetchall()
    conn.close()

    if not tests:
        await call.message.edit_text("Hozircha bazada hech qanday test yo'q. Avval 'Yangi test yaratish'ni tanlang.")
        return

    builder = InlineKeyboardBuilder()
    for t in tests:
        builder.button(text=t[1], callback_data=f"seltest_{t[0]}")
    builder.adjust(1)
    await call.message.edit_text("Qaysi testga davom qilib qo'shmoqchisiz? Tanlang:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("seltest_"))
async def select_existing_test(call: types.CallbackQuery, state: FSMContext):
    test_id = int(call.data.split("_")[1])
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM tests WHERE id=%s", (test_id,))
    base_name = cursor.fetchone()[0]
    conn.close()
    await state.update_data(base_name=base_name)
    await call.message.edit_text(f"Siz '{base_name}' ni tanladingiz.\n\nEndi savollar oraliqini yozing (Masalan: 50-60 gacha):")
    await state.set_state(CreateQuiz.GET_RANGE)

@dp.message(StateFilter(CreateQuiz.GET_RANGE))
async def get_test_range(message: types.Message, state: FSMContext):
    data = await state.get_data()
    final_test_name = f"{data['base_name']} {message.text}"
    conn = get_db_conn()
    cursor = conn.cursor()
    # O'zgartiriladigan 2 qator:
    cursor.execute("INSERT INTO tests (name, creator_id) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING", (final_test_name, message.from_user.id))
    cursor.execute("SELECT id FROM tests WHERE name=%s", (final_test_name,))
    test_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    await state.update_data(test_id=test_id)
    await message.answer(f"✅ Baza tayyor: *{final_test_name}*\n\n❓ SAVOL rasmini yuboring:", parse_mode="Markdown")
    await state.set_state(CreateQuiz.GET_Q)

@dp.message(StateFilter(CreateQuiz.GET_NEW_NAME))
async def get_new_test_name(message: types.Message, state: FSMContext):
    conn = get_db_conn()
    cursor = conn.cursor()
    # O'zgartiriladigan 2 qator:
    cursor.execute("INSERT INTO tests (name, creator_id) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING", (message.text, message.from_user.id))
    cursor.execute("SELECT id FROM tests WHERE name=%s", (message.text,))
    test_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    await state.update_data(test_id=test_id)
    await message.answer(f"✅ Yangi test ochildi.\n\n❓ SAVOL rasmini yuboring:")
    await state.set_state(CreateQuiz.GET_Q)

@dp.message(F.photo, StateFilter(CreateQuiz.GET_Q))
async def get_q(message: types.Message, state: FSMContext):
    await state.update_data(q=message.photo[-1].file_id)
    await message.answer("✅ TO'G'RI JAVOB (A) rasmini yuboring:")
    await state.set_state(CreateQuiz.GET_A)

@dp.message(F.photo, StateFilter(CreateQuiz.GET_A))
async def get_a(message: types.Message, state: FSMContext):
    await state.update_data(a=message.photo[-1].file_id)
    await message.answer("✅ 1-NOTO'G'RI (B) rasmini yuboring:")
    await state.set_state(CreateQuiz.GET_W1)

@dp.message(F.photo, StateFilter(CreateQuiz.GET_W1))
async def get_w1(message: types.Message, state: FSMContext):
    await state.update_data(w1=message.photo[-1].file_id)
    await message.answer("✅ 2-NOTO'G'RI (C) rasmini yuboring:")
    await state.set_state(CreateQuiz.GET_W2)

@dp.message(F.photo, StateFilter(CreateQuiz.GET_W2))
async def get_w2(message: types.Message, state: FSMContext):
    await state.update_data(w2=message.photo[-1].file_id)
    await message.answer("✅ 3-NOTO'G'RI (D) rasmini yuboring:")
    await state.set_state(CreateQuiz.GET_W3)

@dp.message(F.photo, StateFilter(CreateQuiz.GET_W3))
async def get_w3(message: types.Message, state: FSMContext):
    await state.update_data(w3=message.photo[-1].file_id)
    builder = InlineKeyboardBuilder()
    for t in [30, 60, 120, 180, 300]:
        text = f"{t // 60} daqiqa" if t >= 60 else f"{t} soniya"
        builder.button(text=text, callback_data=f"settime_{t}")
    builder.adjust(2)
    await message.answer("✅ Savol uchun vaqt belgilang:", reply_markup=builder.as_markup())
    await state.set_state(CreateQuiz.GET_TIME)

@dp.callback_query(F.data.startswith("settime_"), StateFilter(CreateQuiz.GET_TIME))
async def process_time_limit(call: types.CallbackQuery, state: FSMContext):
    time_limit = int(call.data.split("_")[1])
    data = await state.get_data()
    conn = get_db_conn()
    cursor = conn.cursor()
    # O'zgartiriladigan qism:
    cursor.execute('''INSERT INTO questions (test_id, creator_id, question_photo_id, correct_answer_photo_id, wrong1_photo_id, wrong2_photo_id, wrong3_photo_id, time_limit) 
                  VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''', 
               (data['test_id'], call.from_user.id, data['q'], data['a'], data['w1'], data['w2'], data['w3'], time_limit))
    conn.commit()
    conn.close()

    builder = InlineKeyboardBuilder()
    builder.button(text="Yana savol qo'shish ➕", callback_data="add_more")
    builder.button(text="Tugatish ⏹", callback_data="finish_add")
    await call.message.edit_text("🎉 Saqlandi! Yana savol qo'shamizmi?", reply_markup=builder.as_markup())
    await call.answer()

@dp.callback_query(F.data == "add_more")
async def add_more_q(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("❓ Keyingi SAVOL rasmini yuboring:")
    await state.set_state(CreateQuiz.GET_Q)
    await call.answer()

@dp.callback_query(F.data == "finish_add")
async def finish_add(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("✅ Yaratish yakunlandi. /start orqali ishlashingiz mumkin.")
    await call.answer()

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM tests")
    tests = cursor.fetchall()
    conn.close()

    if not tests:
        await message.answer("Hozircha bazada testlar yo'q. /add orqali yarating.")
        return

    builder = InlineKeyboardBuilder()
    for t in tests:
        builder.button(text=t[1], callback_data=f"starttest_{t[0]}")
    builder.adjust(1)
    await message.answer("👋 Ishlamoqchi bo'lgan testni tanlang:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("starttest_"))
async def start_specific_test(call: types.CallbackQuery, state: FSMContext):
    test_id = int(call.data.split("_")[1])
    conn = get_db_conn()
    cursor = conn.cursor()
    # SHU QATORNI ALMASHTIRING:
    cursor.execute("SELECT id, test_id, question_photo_id, correct_answer_photo_id, wrong1_photo_id, wrong2_photo_id, wrong3_photo_id, time_limit, creator_id FROM questions WHERE test_id=%s ORDER BY id", (test_id,))
    questions = cursor.fetchall()
    conn.close()

    if not questions:
        await call.answer("Bu testda savollar yo'q!", show_alert=True)
        return

    await state.update_data(questions=questions, current_idx=0, score=0)
    await call.message.edit_text("🚀 Test boshlandi! Omad.")
    await send_current_question(call.message, state)
    await call.answer()

async def send_current_question(message: types.Message, state: FSMContext):
    data = await state.get_data()
    questions = data['questions']
    idx = data['current_idx']

    if idx >= len(questions):
        await message.answer(f"🏁 Test yakunlandi!\n\nSiz {len(questions)} ta savoldan {data['score']} tasiga to'g'ri javob berdingiz.")
        builder = InlineKeyboardBuilder()
        builder.button(text="Bosh menuga qaytish 🔙", callback_data="back_to_menu")
        await message.answer("Yana test ishlaysizmi?", reply_markup=builder.as_markup())
        await state.clear()
        return

    q_row = questions[idx]
    time_limit = q_row[7]

    options = [
        (q_row[3], True),  
        (q_row[4], False), 
        (q_row[5], False), 
        (q_row[6], False)  
    ]
    random.shuffle(options)

    correct_idx = 0
    for i, opt in enumerate(options):
        if opt[1]:
            correct_idx = i
            break
            
    await state.update_data(correct_btn_index=correct_idx)

    status_msg = await message.answer(f"⏳ {idx+1}-savol yuklanmoqda...")
    
    merged_photo = await merge_quiz_images(bot, q_row[2], options[0][0], options[1][0], options[2][0], options[3][0])
    
    await status_msg.delete()
    await message.answer_photo(merged_photo, caption=f"❓ {idx+1}-SAVOL.\nRasmda variantlar tepadan pastga qarab joylashgan.")

    poll_options = ["1-chi rasm", "2-chi rasm", "3-chi rasm", "4-chi rasm"]
    quiz_poll = await message.answer_poll(
        question=f"{idx+1}-savol: Qaysi rasmda to'g'ri javob berilgan?",
        options=poll_options,
        is_anonymous=False,
        type="quiz",
        correct_option_id=correct_idx,
        open_period=time_limit
    )

    await state.update_data(current_poll_id=quiz_poll.poll.id)
    await state.set_state(SolveQuiz.IN_PROGRESS)

    builder = InlineKeyboardBuilder()
    builder.button(text="Keyingi savol ➡️", callback_data="next_q_quiz")
    await message.answer("Javobni belgilab bo'lgach, keyingi savolga o'tish uchun bosing 👇", reply_markup=builder.as_markup())

@dp.poll_answer()
async def handle_poll_answer(poll_answer: types.PollAnswer, state: FSMContext):
    data = await state.get_data()
    if not data:
        return
    if poll_answer.poll_id == data.get('current_poll_id'):
        if poll_answer.option_ids[0] == data.get('correct_btn_index'):
            await state.update_data(score=data.get('score', 0) + 1)

@dp.callback_query(F.data == "next_q_quiz", StateFilter(SolveQuiz.IN_PROGRESS))
async def go_next_quiz(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(current_idx=data['current_idx'] + 1)
    await call.message.delete()
    await send_current_question(call.message, state)
    await call.answer()

@dp.callback_query(F.data.startswith("delq_"))
async def process_delete_question(call: types.CallbackQuery):
    _, q_id, creator_id = call.data.split("_")
    
    # RUXSATNI TEKSHIRAMIZ: Faqat Admin yoki Testni yaratgan odam o'chira oladi!
    if call.from_user.id == ADMIN_ID or str(call.from_user.id) == creator_id:
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM questions WHERE id = %s", (int(q_id),))
        conn.commit()
        conn.close()
        
        # Ekrandagi tugmani va yozuvni o'chirib tashlab ogohlantiramiz
        await call.answer("✅ Savol muvaffaqiyatli o'chirildi!", show_alert=True)
        await call.message.edit_text("🚫 Bu savol ma'lumotlar bazasidan o'chirib tashlandi.\nSiz bemalol 'Keyingi savol'ga o'tishingiz mumkin.")
    else:
        # Begona odam bossa chiqadigan ogohlantirish (show_alert=True qilingani uchun tepadan qizil bo'lib chiqadi)
        await call.answer("❌ Kechirasiz, sizda bu savolni o'chirish huquqi yo'q. Faqat admin yoki savol muallifi o'chira oladi!", show_alert=True)


@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await cmd_start(call.message, state)
    await call.answer()

# --- SERVER UXLAB QOLMASLIGI UCHUN WEB JAVOB ---
async def handle_ping(request):
    return web.Response(text="Bot 24/7 ishlab turibdi! Supabase ulanishi joyida.")

async def main():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

    await dp.start_polling(bot, allowed_updates=["message", "callback_query", "poll_answer", "poll"])

if __name__ == "__main__":
    asyncio.run(main())