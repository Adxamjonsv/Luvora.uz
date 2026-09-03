# -*- coding: utf-8 -*-
# ============================================================================
#  Luvora — tanishuv boti (aiogram 3.x, ma'lumotlar bazasi = JSON)
#  Ikki tilli: O'zbek va Rus. Til tanlashga qarab bot o'sha tilda ishlaydi.
#
#  QANDAY ISHGA TUSHIRISH:
#    1) pip install aiogram aiohttp
#    2) BOT_TOKEN ga o'z tokeningni yoz (@BotFather dan olinadi)
#    3) ADMINS ga o'z Telegram ID ni yoz (@userinfobot dan bilib olasan)
#    4) python dvinchik_bot.py
# ============================================================================

import asyncio
import json
import os
import math
import hmac
import hashlib
import logging
from datetime import datetime
from urllib.parse import parse_qsl

import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    FSInputFile,
    BotCommand,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
    InputMediaVideo,
    WebAppInfo,
    MenuButtonWebApp,
    MenuButtonCommands,
    LabeledPrice,
    PreCheckoutQuery,
)

# ============================== SOZLAMALAR ==================================

BOT_TOKEN = "8720127945:AAF23YOS493GjzbWMmdj77_hRRlAVTXEWlg"   # <-- bot tokeni
ADMINS = [5037976320]                            # <-- o'z Telegram ID ing (bir nechta bo'lishi mumkin)
DB_FILE = "database.json"                        # ma'lumotlar bazasi fayli
MAX_MEDIA = 3                                     # anketaga nechta foto/video qo'shsa bo'ladi
# Moderatsiya (yangi anketalar) qayerga kelsin: None => birinchi adminning shaxsiy DM'i.
# Maxfiy admin-guruhga yo'naltirish uchun shu yerga guruh ID sini yoz (masalan -1001234567890).
MOD_CHAT_ID = None

# ---- Majburiy kanal obunasi ----
# Ro'yxatdan o'tgach shu necha kundan keyin kanalga obuna talab qilinadi.
# MUHIM: obunani tekshirish uchun bot @LuvoraOfficial kanaliga ADMIN qilib qo'shilishi shart!
CHANNEL_USERNAME = "LuvoraOfficial"                 # kanal @username (masalan LuvoraOfficial)
CHANNEL_URL = "https://t.me/LuvoraOfficial"          # kanal havolasi
CHANNEL_AFTER_DAYS = 0                               # necha kundan keyin obuna so'ralsin (TEST: 0, keyin 3 qilinadi)
AUTO_POST_HOUR = 12                                  # kanalga avtomatik post soati (0-23, mahalliy vaqt)
AUTO_POST_ENABLED = True                             # avtomatik kanal postlarini yoqish/o'chirish

# ---- Mini App (Telegram Web App) ----
# cloudflared tunnel bergan https manzilni shu yerga yoz (masalan "https://abc-xyz.trycloudflare.com").
# Bo'sh bo'lsa Mini App tugmasi ko'rsatilmaydi, bot oddiy rejimda ishlayveradi.
WEBAPP_URL = ""
WEB_PORT = 8080   # ichki web-server porti (cloudflared shu portga ulanadi)
FREE_SWIPE_LIMIT = 100   # bepul: 24 soatda maksimal layk+dislayk zaxirasi (Premium — cheksiz)
SWIPE_REGEN_MS = 24 * 3600 * 1000 // FREE_SWIPE_LIMIT   # 1 ta tiklanish vaqti (~14.4 daqiqa)

logging.basicConfig(level=logging.INFO)

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
BOT_USERNAME = ""  # startda to'ldiriladi

# ============================== MA'LUMOTLAR BAZASI (JSON) ==================

def load_db() -> dict:
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"users": {}}


def save_db():
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


db = load_db()


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def get_user(uid) -> dict:
    return db["users"].get(str(uid))


def purge_user(uid) -> bool:
    """Foydalanuvchini va u bilan bog'liq hamma narsani butunlay o'chiradi.
    Qaytgan qiymat: bor edimi (True) yoki yo'q (False)."""
    uid = str(uid)
    existed = uid in db.get("users", {})
    db.get("users", {}).pop(uid, None)
    for other in db.get("users", {}).values():
        if isinstance(other.get("matches"), list):
            other["matches"] = [m for m in other["matches"] if str(m) != uid]
        if isinstance(other.get("seen"), list):
            other["seen"] = [s for s in other["seen"] if str(s) != uid]
        if isinstance(other.get("likes_incoming"), list):
            other["likes_incoming"] = [l for l in other["likes_incoming"] if str(l.get("from")) != uid]
    msgs = db.get("messages", {})
    for k in [k for k in msgs if uid in k.split(":")]:
        msgs.pop(k, None)
    db.get("pending_ref", {}).pop(uid, None)
    save_db()
    return existed


# ============================== TILLAR / I18N ==============================

# 12 til (tugma yozuvi). Faqat Rus tanlansa — ruscha, qolgan hammasi — o'zbekcha.
LANGUAGES = [
    "🇺🇿 O'zbek", "🇷🇺 Русский",
    "🇬🇧 English", "🇰🇿 Қазақша",
    "🇰🇬 Кыргызча", "🇹🇯 Тоҷикӣ",
    "🇹🇲 Türkmen", "🇦🇿 Azərbaycan",
    "🇦🇲 Հայերեն", "🇬🇪 ქართული",
    "🇺🇦 Українська", "🇧🇾 Беларуская",
]


def norm_lang(s) -> str:
    """Til satridan kodni aniqlash: rus bo'lsa 'ru', qolgani 'uz'."""
    if s and "Русский" in s:
        return "ru"
    return "uz"


def user_lng(uid) -> str:
    p = get_user(uid)
    return norm_lang(p.get("language")) if p else "uz"


async def ulng(message: Message, state: FSMContext = None) -> str:
    """Foydalanuvchi tilini aniqlash: avval profil, keyin FSM ma'lumoti."""
    p = get_user(message.from_user.id)
    if p and p.get("language"):
        return norm_lang(p["language"])
    if state is not None:
        d = await state.get_data()
        if d.get("language"):
            return norm_lang(d["language"])
    return "uz"


# --- Ikki tilli matnlar ---
TEXTS = {
    "lang_wrong": {
        "uz": "Pastdagi tugma orqali tilni tanla 👇",
        "ru": "Выбери язык кнопкой ниже 👇",
    },
    "agree": {
        "uz": ("❗️ Esda tut, internetda odamlar o'zini boshqacha ko'rsatishi mumkin.\n"
               "Bot shaxsiy ma'lumotlarni so'ramaydi va hech qanday hujjat bo'yicha shaxsni tekshirmaydi.\n"
               "Davom etsang, foydalanuvchi shartlari va maxfiylik siyosatini qabul qilasan."),
        "ru": ("❗️ Помните, что в интернете люди могут выдавать себя за других.\n"
               "Бот не запрашивает личные данные и не идентифицирует пользователей по каким-либо документам.\n"
               "Продолжая, вы принимаете пользовательское соглашение и политику конфиденциальности."),
    },
    "age_q": {"uz": "Yoshing nechada?", "ru": "Сколько тебе лет?"},
    "age_wrong": {
        "uz": "Yoshingni raqamda kirit (masalan 22) yoki tugmani bos 👇",
        "ru": "Введи возраст числом (например 22) или нажми кнопку 👇",
    },
    "gender_q": {"uz": "Endi jinsingni tanlaymiz", "ru": "Теперь определимся с полом"},
    "interest_q": {"uz": "Kim bilan tanishmoqchisan?", "ru": "Кто тебе интересен?"},
    "city_q": {
        "uz": "Qaysi shahardansan?\n(tugmani bos yoki shahar nomini matnda yoz)",
        "ru": "Из какого ты города?\n(нажми кнопку или напиши название города текстом)",
    },
    "city_notfound": {
        "uz": "Shaharni aniqlay olmadim 🙈 Shahar nomini matnda yoz:",
        "ru": "Не смог определить город 🙈 Напиши название своего города текстом:",
    },
    "name_q": {"uz": "Seni qanday atashim mumkin?", "ru": "Как мне тебя называть?"},
    "about_q": {
        "uz": ("O'zing haqingda va kimni izlayotganing, nima qilishni yoqtirishing haqida yoz. "
               "Bu senga mos hamroh topishga yordam beradi."),
        "ru": ("Расскажи о себе и кого хочешь найти, чем предлагаешь заняться. "
               "Это поможет лучше подобрать тебе компанию."),
    },
    "photo_q": {
        "uz": "Endi foto yubor yoki video yozib jo'nat 👍 (15 sekundgacha), uni boshqalar ko'radi",
        "ru": "Теперь пришли фото или запиши видео 👍 (до 15 сек), его будут видеть другие пользователи",
    },
    "media_added_max": {
        "uz": "Foto qo'shildi – {n} / {mx}.",
        "ru": "Фото добавлено – {n} из {mx}.",
    },
    "media_added_more": {
        "uz": "Foto qo'shildi – {n} / {mx}. Yana bittami?",
        "ru": "Фото добавлено – {n} из {mx}. Еще одно?",
    },
    "need_one_media": {
        "uz": "Kamida bitta foto yoki video yubor 🙏",
        "ru": "Пришли хотя бы одно фото или видео 🙏",
    },
    "send_photo_wrong": {"uz": "Foto yoki video yubor 👍", "ru": "Пришли фото или видео 👍"},
    "phone_q": {
        "uz": ("Anketani tasdiqlash uchun telefon raqamingni yuborishing kerak. "
               "Uni boshqa foydalanuvchilar ko'rmaydi."),
        "ru": ("Мне нужен твой номер телефона для подтверждения анкеты. "
               "Его не увидят другие пользователи."),
    },
    "phone_wrong": {
        "uz": "📱 Telefon raqamimni yuborish tugmasini bos",
        "ru": "Нажми кнопку 📱 Отправить мой номер телефона",
    },
    "verify_q": {
        "uz": ("Deyarli tayyor! 🎥 Haqiqiy odam ekaningni tasdiqlash uchun "
               "video-krujok (video-xabar, 15 sekundgacha) yozib yubor.\n\n"
               "Qanday yoziladi: kiritish maydonining o'ng tomonidagi 🎤 belgisini bos — u "
               "yumaloq kamera 🔵 ga aylanadi, keyin bosib ushlab qisqa video yoz."),
        "ru": ("Почти готово! 🎥 Запиши видео-кружочек (видео-сообщение, до 15 сек), "
               "чтобы подтвердить, что ты настоящий человек.\n\n"
               "Как записать: нажми на иконку 🎤 справа в поле ввода — она станет круглой "
               "камерой 🔵, затем зажми и запиши короткое видео."),
    },
    "verify_wrong": {
        "uz": ("Aynan video-krujok 🎥 (video-xabar) kerak, oddiy video yoki matn emas. "
               "Shu tarzda haqiqiy odam ekaningni tekshiramiz 🙂"),
        "ru": ("Нужен именно видео-кружочек 🎥 (видео-сообщение), а не обычное видео или текст. "
               "Так мы проверяем, что ты реальный человек 🙂"),
    },
    "profile_preview": {"uz": "Anketang shunday ko'rinadi:", "ru": "Так выглядит твоя анкета:"},
    "all_correct": {"uz": "Hammasi to'g'rimi?", "ru": "Все верно?"},
    "saved": {"uz": "Zo'r! Anketa saqlandi ✅", "ru": "Отлично! Анкета сохранена ✅"},
    "refill_age": {
        "uz": "Yaxshi, qaytadan to'ldiramiz.\nYoshing nechada?",
        "ru": "Хорошо, заполним заново.\nСколько тебе лет?",
    },
    "welcome_back": {
        "uz": "Qaytganing bilan! 👋 Qidiruvni davom ettiramiz.",
        "ru": "С возвращением! 👋 Продолжаем поиск.",
    },
    "no_new": {
        "uz": "Hozircha yangi anketa yo'q 🙌 Keyinroq kir.",
        "ru": "Пока новых анкет нет 🙌 Загляни позже.",
    },
    "sleep_header": {
        "uz": "Kimdir anketangni ko'rguncha kutamiz",
        "ru": "Подождем пока кто-то увидит твою анкету",
    },
    "sleep_body": {
        "uz": ("1. Anketalarni ko'rish.\n"
               "2. Mening anketam.\n"
               "3. Endi hech kimni qidirmayman.\n"
               "***\n"
               "4. Do'stlaringni taklif qil — ko'proq layk ol 😎."),
        "ru": ("1. Смотреть анкеты.\n"
               "2. Моя анкета.\n"
               "3. Я больше не хочу никого искать.\n"
               "***\n"
               "4. Пригласи друзей - получи больше лайков 😎."),
    },
    "myp_body": {
        "uz": ("1. Anketalarni ko'rish.\n"
               "2. Anketani qaytadan to'ldirish.\n"
               "3. Foto/videoni o'zgartirish.\n"
               "4. Anketa matnini o'zgartirish.\n"
               "5 🌐 Tilni o'zgartirish."),
        "ru": ("1. Смотреть анкеты.\n"
               "2. Заполнить анкету заново.\n"
               "3. Изменить фото/видео.\n"
               "4. Изменить текст анкеты.\n"
               "5 🌐 Изменить язык."),
    },
    "lang_choose": {
        "uz": "Tilni tanla 👇",
        "ru": "Выбери язык 👇",
    },
    "lang_changed": {
        "uz": "Til o'zgartirildi ✅",
        "ru": "Язык изменён ✅",
    },
    "profile_notfound": {
        "uz": "Anketa topilmadi. To'ldirish uchun /start yoz.",
        "ru": "Анкета не найдена. Напиши /start, чтобы заполнить.",
    },
    "liked_notify": {
        "uz": "💌 Sen kimgadir yoqding! Ko'rish uchun /likes yoz.",
        "ru": "💌 Ты кому-то понравился(ась)! Напиши /likes, чтобы посмотреть.",
    },
    "use_buttons": {
        "uz": "Pastdagi tugmalardan foydalan 👇",
        "ru": "Пользуйся кнопками ниже 👇",
    },
    "write_msg": {
        "uz": "Bu foydalanuvchiga xabar yoz\nyoki qisqa video (15 sekundgacha) yozib yubor",
        "ru": "Напиши сообщение для этого пользователя\nили запиши короткое видео(до 15сек)",
    },
    "like_sent": {"uz": "Layk yuborildi, javobni kutamiz.", "ru": "Лайк отправлен, ждем ответа."},
    "hidden_msg": {
        "uz": ("Endi hech kim anketangni ko'rmaydi 🙈\n"
               "Qaytishni xohlasang — pastdagi tugmani bos."),
        "ru": ("Больше никто не увидит твою анкету 🙈\n"
               "Когда захочешь вернуться — нажми кнопку ниже."),
    },
    "invite": {
        "uz": ("Do'stlaringni taklif qil va ko'proq layk ol 😎\n\n"
               "Sening havolang:\n{link}\n\n"
               "Taklif qilingan do'stlar: {cnt}"),
        "ru": ("Приглашай друзей и получай больше лайков 😎\n\n"
               "Твоя ссылка:\n{link}\n\n"
               "Уже приглашено друзей: {cnt}"),
    },
    "choose_item": {
        "uz": "Tugma orqali bo'limni tanla 👇",
        "ru": "Выбери пункт кнопкой 👇",
    },
    "back_in_game": {"uz": "Yana o'yindamiz! 🎉", "ru": "Снова в игре! 🎉"},
    "press_return": {
        "uz": "Qaytish uchun tugmani bos 👇",
        "ru": "Нажми кнопку, чтобы вернуться 👇",
    },
    "media_updated": {"uz": "Foto/video yangilandi ✅", "ru": "Фото/видео обновлены ✅"},
    "about_updated": {"uz": "Anketa matni yangilandi ✅", "ru": "Текст анкеты обновлён ✅"},
    "no_likes": {
        "uz": "Hozircha hech kim anketangni layk qilmadi 🙈",
        "ru": "Пока никто не лайкнул твою анкету 🙈",
    },
    "your_liked": {"uz": "💌 Anketang kimgadir yoqdi!", "ru": "💌 Твоя анкета кому-то понравилась!"},
    "someone_liked": {"uz": "💌 Seni kimdir layk qildi!", "ru": "💌 Тебя кто-то лайкнул!"},
    "msg_label": {"uz": "💬 Xabar: {text}", "ru": "💬 Сообщение: {text}"},
    "mutual": {
        "uz": "O'zaro yoqdingiz! 🎉 Birinchi bo'lib yoz: {contact}",
        "ru": "Это взаимно! 🎉 Напиши первым(ой): {contact}",
    },
    "mutual_notify": {
        "uz": "Simpatiyangga o'zaro javob berildi! 🎉 Yoz: {contact}",
        "ru": "Твою симпатию оценили взаимно! 🎉 Напиши: {contact}",
    },
    "choose_button": {"uz": "Tugma orqali tanla 👇", "ru": "Выбери кнопкой 👇"},
    "fallback_reg": {
        "uz": "Klaviaturadagi tugmani bos 🙂 yoki /start",
        "ru": "Нажми кнопку на клавиатуре 🙂 или /start",
    },
    "fallback_unreg": {
        "uz": "Boshlash uchun /start yoz 🙂",
        "ru": "Напиши /start, чтобы начать 🙂",
    },
    "fill_first": {
        "uz": "Avval anketani to'ldir: /start",
        "ru": "Сначала заполни анкету: /start",
    },
    "ref_credited": {
        "uz": "🎉 Havolang orqali do'sting ro'yxatdan o'tdi! Reytingga +1.",
        "ru": "🎉 По твоей ссылке зарегистрировался друг! +1 к рейтингу.",
    },
    "pending_user": {
        "uz": "Anketang tekshiruvga yuborildi ⏳\nAdmin video-krujogingni ko'rib chiqadi. Biroz kutib tur — tasdiqlangach xabar beramiz.",
        "ru": "Твоя анкета отправлена на проверку ⏳\nАдмин посмотрит твой видео-кружочек. Немного подожди — сообщим после подтверждения.",
    },
    "approved_user": {
        "uz": "✅ Anketang tasdiqlandi! Endi qidiruvni boshlaymiz. /start bosib davom et.",
        "ru": "✅ Твоя анкета подтверждена! Теперь начинаем поиск. Нажми /start, чтобы продолжить.",
    },
    "rejected_user": {
        "uz": "❌ Anketang tasdiqlanmadi.\nIltimos, /start bosib qaytadan aniq video-krujok yubor (yuzing ko'rinib tursin).",
        "ru": "❌ Твоя анкета не подтверждена.\nПожалуйста, нажми /start и запиши новый чёткий видео-кружочек (лицо должно быть видно).",
    },
}


def t(key, lng="uz", **kw) -> str:
    s = TEXTS[key].get(lng) or TEXTS[key]["uz"]
    return s.format(**kw) if kw else s


# --- Start bosishdan oldingi matnlar (har doim IKKI TILDA) ---
LANG_PROMPT = "Tilni tanla 👇\nВыберите язык 👇"

WELCOME_BILINGUAL = (
    "🇺🇿 Luvora'ga xush kelibsan! 😍\n"
    "Men senga juftlik yoki shunchaki do'st topishga yordam beraman 👫\n"
    "\n"
    "🇷🇺 Добро пожаловать в Luvora! 😍\n"
    "Я помогу найти тебе пару или просто друзей 👫"
)


# ============================== TUGMA VARIANTLARI ==========================
# Har bir tugma ikki tilda. Filtrlar ikkala variantni ham tushunadi.

BTN = {
    "start":      {"uz": "👌 boshladik",              "ru": "👌 давай начнем"},
    "gender_f":   {"uz": "Men qizman",               "ru": "Я девушка"},
    "gender_m":   {"uz": "Men yigitman",             "ru": "Я парень"},
    "int_f":      {"uz": "Qizlar",                    "ru": "Девушки"},
    "int_m":      {"uz": "Yigitlar",                  "ru": "Парни"},
    "int_any":    {"uz": "Farqi yo'q",               "ru": "Все равно"},
    "location":   {"uz": "📍 Joylashuvimni yuborish", "ru": "📍 Отправить мои координаты"},
    "skip":       {"uz": "O'tkazib yuborish",        "ru": "Пропустить"},
    "save_photo": {"uz": "Tayyor, fotoni saqlash",   "ru": "Это все, сохранить фото"},
    "phone":      {"uz": "📱 Telefon raqamimni yuborish", "ru": "📱 Отправить мой номер телефона"},
    "yes":        {"uz": "Ha",                        "ru": "Да"},
    "change":     {"uz": "Anketani o'zgartirish",    "ru": "Изменить анкету"},
    "back":       {"uz": "Orqaga qaytish",           "ru": "Вернуться назад"},
    "hidden_ret": {"uz": "🚀 Qidiruvga qaytish",     "ru": "🚀 Вернуться в поиск"},
    "like_yes":   {"uz": "❤️ Javob berish",          "ru": "❤️ Ответить взаимностью"},
    "like_skip":  {"uz": "👎 O'tkazish",             "ru": "👎 Пропустить"},
    "like_back":  {"uz": "🔙 Orqaga",                "ru": "🔙 Назад"},
}


def bset(*keys) -> set:
    """Berilgan tugma(lar)ning ikkala tildagi variantlari to'plami."""
    out = set()
    for k in keys:
        out.update(BTN[k].values())
    return out


# Filtr to'plamlari
B_START = bset("start")
B_GENDER = bset("gender_f", "gender_m")
B_GENDER_F = set(BTN["gender_f"].values())
B_INTEREST = bset("int_f", "int_m", "int_any")
B_SKIP = bset("skip")
B_SAVE_PHOTO = bset("save_photo")
B_YES = bset("yes")
B_CHANGE = bset("change")
B_BACK = bset("back")
B_HIDDEN_RET = bset("hidden_ret")
B_LIKE_YES = bset("like_yes")
B_LIKE_SKIP = bset("like_skip")
B_LIKE_BACK = bset("like_back")

# Ichki (kanonik) qiymatlar uchun moslik
INTEREST_MAP = {
    BTN["int_f"]["uz"]: "Qizlar", BTN["int_f"]["ru"]: "Qizlar",
    BTN["int_m"]["uz"]: "Yigitlar", BTN["int_m"]["ru"]: "Yigitlar",
    BTN["int_any"]["uz"]: "Farqi yo'q", BTN["int_any"]["ru"]: "Farqi yo'q",
}


# ============================== HOLATLAR (FSM) =============================

class Reg(StatesGroup):
    language = State()
    start = State()
    agree = State()
    age = State()
    gender = State()
    interest = State()
    city = State()
    name = State()
    about = State()
    photo = State()
    phone = State()
    verify = State()
    confirm = State()


class Browse(StatesGroup):
    viewing = State()
    messaging = State()
    menu = State()
    my_profile = State()
    hidden = State()


class Likes(StatesGroup):
    viewing = State()


class Edit(StatesGroup):
    photo = State()
    about = State()


class Settings(StatesGroup):
    language = State()


class Admin(StatesGroup):
    menu = State()
    broadcast = State()
    ban = State()
    check = State()
    pro = State()
    delete = State()


# ============================== KLAVIATURALAR =============================

def rkb(rows, one_time=False) -> ReplyKeyboardMarkup:
    keyboard = [[KeyboardButton(text=t) for t in row] for row in rows]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True, one_time_keyboard=one_time)


def lang_kb() -> ReplyKeyboardMarkup:
    rows = [LANGUAGES[i:i + 2] for i in range(0, len(LANGUAGES), 2)]
    return rkb(rows)


def start_kb(lng):
    return rkb([[BTN["start"][lng]]])


def agree_kb():
    return rkb([["👌 Ok"]])


def age_kb():
    return rkb([["18", "19", "20", "21"],
                ["22", "23", "24", "25"],
                ["26", "27", "28", "29"]])


def gender_kb(lng):
    return rkb([[BTN["gender_f"][lng], BTN["gender_m"][lng]]])


def interest_kb(lng):
    return rkb([[BTN["int_f"][lng], BTN["int_m"][lng]], [BTN["int_any"][lng]]])


def city_kb(lng):
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN["location"][lng], request_location=True)]],
        resize_keyboard=True,
    )


def name_kb(tg_name: str):
    return rkb([[tg_name]]) if tg_name else ReplyKeyboardRemove()


def about_kb(lng):
    return rkb([[BTN["skip"][lng]]])


def save_photo_kb(lng):
    return rkb([[BTN["save_photo"][lng]]])


def phone_kb(lng):
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN["phone"][lng], request_contact=True)]],
        resize_keyboard=True,
    )


def confirm_kb(lng):
    return rkb([[BTN["yes"][lng], BTN["change"][lng]]])


def browse_kb():
    return rkb([["❤️", "💌/📹"], ["👎", "💤"]])


def back_kb(lng):
    return rkb([[BTN["back"][lng]]])


def sleep_kb():
    return rkb([["1 🚀", "2"], ["3", "4"]])


def my_profile_kb():
    return rkb([["1", "2"], ["3", "4"], ["5 🌐"]])


def hidden_kb(lng):
    return rkb([[BTN["hidden_ret"][lng]]])


def likes_kb(lng):
    return rkb([[BTN["like_yes"][lng]], [BTN["like_skip"][lng], BTN["like_back"][lng]]])


def admin_kb():
    return rkb([["📊 Statistika", "👥 Foydalanuvchilar"],
                ["🎥 Tekshirish", "📢 Xabar tarqatish"],
                ["🚫 Ban/Unban", "👑 Premium (Pro)"],
                ["🗑 Anketa o'chirish", "📌 Kanalga post"],
                ["🔙 Chiqish"]])


# ============================== MA'LUMOTNOMALAR (DEMO) ====================

DEMO_PROFILES = {
    "demo1": {"id": "demo1", "name": "Anna", "age": 20, "gender": "qiz",
              "city": "Toshkent", "lat": 41.311, "lon": 69.240,
              "about": "Kofe, kitob va kechki sayrni yaxshi ko'raman ☕📚",
              "media": [{"type": "photo", "url": "https://picsum.photos/seed/anna/600/800"}]},
    "demo2": {"id": "demo2", "name": "Maria", "age": 23, "gender": "qiz",
              "city": "Toshkent", "lat": 41.320, "lon": 69.250,
              "about": "Kinoga hamroh qidiryapman 🎬",
              "media": [{"type": "photo", "url": "https://picsum.photos/seed/maria/600/800"}]},
    "demo3": {"id": "demo3", "name": "Olga", "age": 25, "gender": "qiz",
              "city": "Samarqand", "lat": 39.627, "lon": 66.975,
              "about": "Rassomman, mushuklar va jazni yaxshi ko'raman 🎷🐈",
              "media": [{"type": "photo", "url": "https://picsum.photos/seed/olga/600/800"}]},
    "demo4": {"id": "demo4", "name": "Dilshod", "age": 24, "gender": "yigit",
              "city": "Toshkent", "lat": 41.315, "lon": 69.245,
              "about": "Sport, musiqa, sayohat. Kel do'st bo'laylik 🤝",
              "media": [{"type": "photo", "url": "https://picsum.photos/seed/dmitry/600/800"}]},
    "demo5": {"id": "demo5", "name": "Aziz", "age": 27, "gender": "yigit",
              "city": "Toshkent", "lat": 41.300, "lon": 69.230,
              "about": "Kunduzi dasturchi, kechqurun gitarachi 🎸",
              "media": [{"type": "photo", "url": "https://picsum.photos/seed/ivan/600/800"}]},
}


def seed_demo():
    for uid, p in DEMO_PROFILES.items():
        if uid not in db["users"]:
            prof = dict(p)
            prof.update({
                "username": None, "interest": "Farqi yo'q", "phone": None,
                "registered": True, "approved": True, "banned": False, "hidden": False,
                "seen": [], "likes_incoming": [], "created": today(),
                "ref_count": 0, "language": "🇺🇿 O'zbek",
            })
            db["users"][uid] = prof
    save_db()


# --- 300 ta boshlang'ich (seed) qiz anketasi: lenta bo'sh ko'rinmasligi uchun ---
SEED_NAMES = [
    "Malika", "Nilufar", "Zarina", "Dilnoza", "Sevara", "Gulnora", "Kamola", "Feruza",
    "Shahzoda", "Madina", "Nozima", "Charos", "Robiya", "Sabina", "Dildora", "Mohira",
    "Aziza", "Gulbahor", "Nargiza", "Mavluda", "Yulduz", "Ziyoda", "Munisa", "Sitora",
    "Barno", "Dilfuza", "Rayhona", "Xushnuda", "Iroda", "Zilola", "Diyora", "Laylo",
    "Maftuna", "Odina", "Ruxshona", "Umida", "Vasila", "Xurshida", "Zebo", "Adiba",
    "Bonu", "Dinora", "Gavhar", "Hulkar", "Komila", "Lobar", "Mehri", "Nozanin",
    "Ozoda", "Parizoda", "Ra'no", "Shahnoza", "Tabassum", "Umida", "Xosiyat", "Yosuman",
    "Anna", "Alina", "Kristina", "Viktoriya", "Diana", "Yana", "Kamila", "Sofiya",
    "Valeriya", "Milana", "Darya", "Polina", "Kseniya", "Elina", "Malika",
]
SEED_ABOUTS = [
    "Kofe, kitob va kechki sayrni yaxshi ko'raman ☕📚",
    "Sayohat va yangi tanishuvlar jonim ✈️ Ijobiy insonlar bilan tanishaman",
    "Musiqa — hayotim 🎧 Samimiy suhbatdosh izlayapman",
    "Sport va sog'lom turmush tarafdoriman 🏃‍♀️",
    "Filmlar va shirinliklar ishqibozi 🍰🎬",
    "Tabiat va suratga olishni sevaman 📷🌿",
    "Mazali taomlar tayyorlashni yoqtiraman 👩‍🍳",
    "Kuluvchan va samimiy insonman 😊 Hazilni tushunaman",
    "Rassomlik va dizayn bilan shug'ullanaman 🎨",
    "Yaxshi kayfiyat va halol munosabat men uchun muhim 💛",
    "Kechki shahar, muzqaymoq va yaxshi suhbat 🌆🍦",
    "Yoga va meditatsiya bilan tinchlik topaman 🧘‍♀️",
    "Gullar, choy va samimiy odamlar 🌸🍵",
    "Hayotni sodda va chiroyli yashashni yoqtiraman ✨",
    "Til o'rganaman va yangi narsalarga qiziqaman 🌍",
]


def seed_bot_profiles(n=300):
    """Toshkentlik n ta boshlang'ich qiz anketasini yaratadi (id 'demo_s...').
    Rasmlar: /seedphoto/<i>.jpg — bu fayllarni miniapp/seed_photos/ ichiga qo'yasiz.
    Real foydalanuvchilar ko'paygan sari bular lentada kamayadi (feed_for real'ni oldin beradi)."""
    import random as _r
    _r.seed(42)  # bir xil natija
    for i in range(1, n + 1):
        uid = f"demo_s{i}"
        if uid in db["users"]:
            continue
        name = _r.choice(SEED_NAMES)
        age = _r.randint(18, 24)
        about = _r.choice(SEED_ABOUTS)
        lat = 41.311 + _r.uniform(-0.08, 0.08)
        lon = 69.240 + _r.uniform(-0.10, 0.10)
        db["users"][uid] = {
            "id": uid, "seed": True, "username": None,
            "name": name, "age": age, "gender": "qiz", "interest": "Yigitlar",
            "city": "Toshkent", "lat": round(lat, 5), "lon": round(lon, 5),
            "about": about,
            "media": [{"type": "photo", "url": f"/seedphoto/{i}.jpg"}],
            "registered": True, "approved": True, "banned": False, "hidden": False,
            "seen": [], "likes_incoming": [], "matches": [],
            "created": today(), "ref_count": 0, "language": "🇺🇿 O'zbek",
            "phone": None, "video_note": None,
        }
    save_db()


# ============================== YORDAMCHILAR ==============================

def haversine(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def location_str(viewer: dict, target: dict) -> str:
    if viewer.get("lat") and target.get("lat"):
        d = haversine(viewer["lat"], viewer["lon"], target["lat"], target["lon"])
        if d < 1:
            return "📍<1 km"
        return f"📍{round(d)} km"
    return target.get("city") or ""


async def reverse_geocode(lat, lon, lng="uz") -> str:
    al = "ru" if lng == "ru" else "uz"
    url = (f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}"
           f"&format=json&accept-language={al}&zoom=10")
    headers = {"User-Agent": "LuvoraBot/1.0"}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=6)) as r:
                data = await r.json()
                a = data.get("address", {})
                return (a.get("city") or a.get("town") or a.get("village")
                        or a.get("municipality") or a.get("state") or "")
    except Exception:
        return ""


async def send_media(chat_id, media, caption=None, markup=None):
    if not media:
        if caption:
            await bot.send_message(chat_id, caption, reply_markup=markup)
        return
    try:
        if len(media) == 1:
            m = media[0]
            src = m.get("file_id") or abs_url(m.get("url"))
            if m["type"] == "photo":
                await bot.send_photo(chat_id, src, caption=caption, reply_markup=markup)
            else:
                await bot.send_video(chat_id, src, caption=caption, reply_markup=markup)
            return
        group = []
        for i, m in enumerate(media):
            src = m.get("file_id") or abs_url(m.get("url"))
            cap = caption if i == 0 else None
            if m["type"] == "photo":
                group.append(InputMediaPhoto(media=src, caption=cap))
            else:
                group.append(InputMediaVideo(media=src, caption=cap))
        await bot.send_media_group(chat_id, group)
    except Exception as e:
        logging.warning("Mediani yuborib bo'lmadi: %s", e)
        text = (caption or "").strip()
        text = (text + "\n\n📷 Foto mavjud emas").strip() if text else "📷 Foto mavjud emas"
        await bot.send_message(chat_id, text, reply_markup=markup)


def norm_gender(g) -> str:
    """Jinsni yagona ko'rinishga keltirish (eski ruscha qiymatlarni ham qo'llaydi)."""
    if g in ("qiz", "девушка", "Я девушка", "Men qizman"):
        return "qiz"
    if g in ("yigit", "парень", "Я парень", "Men yigitman"):
        return "yigit"
    return g or ""


def norm_interest(i) -> str:
    """Qiziqishni yagona ko'rinishga keltirish (eski ruscha qiymatlarni ham qo'llaydi)."""
    if i in ("Qizlar", "Девушки"):
        return "Qizlar"
    if i in ("Yigitlar", "Парни"):
        return "Yigitlar"
    return "Farqi yo'q"


def is_boosted(p) -> bool:
    """Anketa hozir 'boost'da (yuqorida)mi?"""
    try:
        import time as _t
        return float(p.get("boost_until", 0)) > _t.time() * 1000
    except Exception:
        return False


def is_premium(p) -> bool:
    """Foydalanuvchi hozir Premium (obuna faol)mi?"""
    if not p:
        return False
    if p.get("premium"):   # admin /pro
        return True
    try:
        import time as _t
        return float(p.get("premium_until", 0)) > _t.time() * 1000
    except Exception:
        return False


# Telegram Stars mahsulotlari (narx = yulduzcha soni)
STAR_PRODUCTS = {
    "prem7":  {"title": "Luvora Premium — 7 kun", "stars": 169, "days": 7,  "kind": "premium"},
    "prem30": {"title": "Luvora Premium — 1 oy",  "stars": 249, "days": 30, "kind": "premium"},
    "prem90": {"title": "Luvora Premium — 3 oy",  "stars": 599, "days": 90, "kind": "premium"},
    "boost1": {"title": "Boost — 1 soat",         "stars": 99,  "hours": 1, "kind": "boost"},
    "boost6": {"title": "Boost — 6 soat",         "stars": 149, "hours": 6, "kind": "boost"},
}

# Virtual sovg'alar (Stars bilan)
GIFTS = {
    "heart":   {"emoji": "❤️", "name": "Yurak",     "stars": 10},
    "rose":    {"emoji": "🌹", "name": "Atirgul",   "stars": 15},
    "choco":   {"emoji": "🍫", "name": "Shokolad",  "stars": 25},
    "teddy":   {"emoji": "🧸", "name": "Ayiqcha",   "stars": 40},
    "bouquet": {"emoji": "💐", "name": "Guldasta",  "stars": 60},
    "ring":    {"emoji": "💍", "name": "Uzuk",      "stars": 150},
}


def pick_candidate(uid):
    user = get_user(uid)
    seen = set(user.get("seen", []))
    interest = norm_interest(user.get("interest"))

    def matches(p):
        if not p.get("registered") or p.get("banned") or p.get("hidden"):
            return False
        if p.get("approved") is False:   # admin hali tasdiqlamagan
            return False
        g = norm_gender(p.get("gender"))
        # Viewer qiziqishiga qarab jinsni tanlash
        if interest == "Qizlar" and g != "qiz":
            return False
        if interest == "Yigitlar" and g != "yigit":
            return False
        if not passes_filter(user, p):
            return False
        return True

    cands = [(k, p) for k, p in db["users"].items()
             if k != str(uid) and matches(p) and k not in seen]

    if not cands:
        any_valid = [(k, p) for k, p in db["users"].items()
                     if k != str(uid) and matches(p)]
        if any_valid:
            user["seen"] = []
            save_db()
            cands = any_valid
        else:
            return None

    def rank(item):
        p = item[1]
        boost = 0 if is_boosted(p) else 1   # boost'dagilar birinchi
        if user.get("lat") and p.get("lat"):
            d = haversine(user["lat"], user["lon"], p["lat"], p["lon"])
        else:
            d = float("inf")
        return (boost, d)
    cands.sort(key=rank)

    return cands[0]


async def show_next_profile(chat_id, uid, state: FSMContext):
    lng = user_lng(uid)
    user = get_user(uid)
    cand = pick_candidate(uid)
    if not cand:
        await bot.send_message(chat_id, t("no_new", lng))
        await show_sleep_menu(chat_id, state)
        return

    tid, target = cand
    user.setdefault("seen", []).append(tid)
    save_db()

    await state.set_state(Browse.viewing)
    await state.update_data(current=tid)

    await bot.send_message(chat_id, "✨🔍", reply_markup=browse_kb())
    caption = f"{target['name']}, {target['age']}, {location_str(user, target)}"
    if target.get("about"):
        caption += f"\n\n{target['about']}"
    await send_media(chat_id, target.get("media", []), caption=caption)


async def show_sleep_menu(chat_id, state: FSMContext):
    lng = user_lng(chat_id)
    await bot.send_message(chat_id, t("sleep_header", lng))
    await bot.send_message(chat_id, t("sleep_body", lng), reply_markup=sleep_kb())
    await state.set_state(Browse.menu)


async def show_my_profile(chat_id, uid, state: FSMContext):
    lng = user_lng(uid)
    p = get_user(uid)
    if not p:
        await bot.send_message(chat_id, t("profile_notfound", lng))
        return
    await bot.send_message(chat_id, t("profile_preview", lng))
    caption = f"{p.get('name', '—')}, {p.get('age', '—')}, {p.get('city', '')}"
    if p.get("about"):
        caption += f"\n\n{p['about']}"
    await send_media(chat_id, p.get("media", []), caption=caption)
    await bot.send_message(chat_id, t("myp_body", lng), reply_markup=my_profile_kb())
    await state.set_state(Browse.my_profile)


def add_match(a, b):
    """Ikki foydalanuvchini match (o'zaro layk) qilish."""
    ua, ub = get_user(a), get_user(b)
    if ua is not None and str(b) not in ua.setdefault("matches", []):
        ua["matches"].append(str(b))
    if ub is not None and str(a) not in ub.setdefault("matches", []):
        ub["matches"].append(str(a))


async def record_like(from_uid, to_uid, text=None, media=None, gift=False, sup=False):
    target = get_user(to_uid)
    if not target:
        return {"match": False}
    me = get_user(from_uid)

    # O'zaro layk tekshiruvi: target avval meni layk qilganmi?
    reciprocal = me is not None and any(
        l["from"] == str(to_uid) for l in me.get("likes_incoming", [])
    )
    if reciprocal:
        me["likes_incoming"] = [l for l in me.get("likes_incoming", []) if l["from"] != str(to_uid)]
        add_match(from_uid, to_uid)
        save_db()
        # ikkalasига match xabari (faqat ilovada bo'lmasa — spam bo'lmasin)
        for uid, other in ((from_uid, target), (to_uid, me)):
            if not str(uid).startswith("demo") and not is_online(get_user(uid)):
                try:
                    nm = other.get("name", "")
                    await bot.send_message(int(uid), f"💛 Yangi moslik (match)! {nm} bilan mos keldingiz. Ilovada yozing 👇", reply_markup=app_kb())
                except Exception:
                    pass
        return {"match": True}

    # oddiy layk (yoki super layk)
    target.setdefault("likes_incoming", []).append({
        "from": str(from_uid), "text": text, "media": media, "gift": gift, "super": sup, "date": today(),
    })
    save_db()
    if not str(to_uid).startswith("demo") and not is_online(target):
        try:
            if sup:
                msg = "⭐ Sizga SUPER LIKE bosishdi!"
            elif gift:
                msg = "🎁 Sizga sovg'a yuborildi!"
            else:
                msg = t("liked_notify", norm_lang(target.get("language")))
            await bot.send_message(int(to_uid), msg, reply_markup=app_kb())
        except Exception:
            pass
    return {"match": False}


def mod_target() -> int:
    return MOD_CHAT_ID if MOD_CHAT_ID else (ADMINS[0] if ADMINS else None)


def mod_kb(uid) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Ha (tasdiqlash)", callback_data=f"mod:ok:{uid}"),
        InlineKeyboardButton(text="❌ Yo'q (rad etish)", callback_data=f"mod:no:{uid}"),
    ]])


async def send_to_moderation(uid, prof):
    """Yangi anketani admin tekshiruvига yuborish: anketa + foto + krujok + ✅/❌."""
    chat = mod_target()
    if not chat:
        return
    gender = "👩 qiz" if norm_gender(prof.get("gender")) == "qiz" else "👨 yigit"
    uname = f"@{prof['username']}" if prof.get("username") else "—"
    info = (
        "🆕 Yangi anketa — tekshiruv kerak\n\n"
        f"👤 {prof.get('name', '—')}, {prof.get('age', '—')} ({gender})\n"
        f"🏙 {prof.get('city', '—')}\n"
        f"📱 {prof.get('phone') or '—'}\n"
        f"🔗 {uname}\n"
        f"🆔 {uid}"
    )
    if prof.get("about"):
        info += f"\n\n📝 {prof['about']}"
    try:
        await bot.send_message(chat, info)
        if prof.get("media"):
            await send_media(chat, prof["media"], caption="📸 Anketa fotosi")
        if prof.get("video_note"):
            await bot.send_message(chat, "🎥 Video-krujok (haqiqiyligini tekshir):")
            try:
                await bot.send_video_note(chat, prof["video_note"])
            except Exception:
                await bot.send_message(chat, "⚠️ Krujokni yuborib bo'lmadi.")
        else:
            await bot.send_message(chat, "⚠️ Bu foydalanuvchi krujok yozmagan.")
        await bot.send_message(chat, "Tasdiqlaysizmi?", reply_markup=mod_kb(uid))
    except Exception as e:
        logging.warning("Moderatsiyaga yuborib bo'lmadi: %s", e)


@dp.callback_query(F.data.startswith("mod:"))
async def mod_decision(cq: CallbackQuery):
    if cq.from_user.id not in ADMINS:
        await cq.answer("Ruxsat yo'q", show_alert=True)
        return
    try:
        _, action, uid = cq.data.split(":")
    except ValueError:
        await cq.answer()
        return
    p = get_user(uid)
    if not p:
        await cq.answer("Anketa topilmadi", show_alert=True)
        return
    lng = norm_lang(p.get("language"))
    name = p.get("name", uid)
    if action == "ok":
        p["approved"] = True
        save_db()
        try:
            await bot.send_message(int(uid), t("approved_user", lng), reply_markup=app_kb())
        except Exception:
            pass
        try:
            await cq.message.edit_text(f"✅ Tasdiqlandi: {name} ({uid})")
        except Exception:
            pass
        await cq.answer("Tasdiqlandi ✅")
    else:
        p["approved"] = False
        save_db()
        try:
            await bot.send_message(int(uid), t("rejected_user", lng))
        except Exception:
            pass
        try:
            await cq.message.edit_text(f"❌ Rad etildi: {name} ({uid})")
        except Exception:
            pass
        await cq.answer("Rad etildi ❌")


# ============================== /start =====================================

def app_kb():
    """Ilovani ochish uchun inline tugma (WEBAPP_URL bo'lsa)."""
    if WEBAPP_URL:
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="💞 Luvora'ni ochish", web_app=WebAppInfo(url=WEBAPP_URL))
        ]])
    return None


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, command: CommandObject):
    await state.clear()
    uid = message.from_user.id

    # Referal: keyinroq (ilovada ro'yxatdan o'tganda) hisoblash uchun saqlaymiz
    if command.args and command.args.startswith("ref"):
        ref = command.args[3:]
        if ref and ref != str(uid):
            db.setdefault("pending_ref", {})[str(uid)] = ref
            save_db()

    # Ro'yxatdan o'tgan, lekin tasdiqlanmagan bo'lsa — tasdiqlashni yakunlaymiz
    ustart = get_user(uid)
    if ustart and ustart.get("registered"):
        if not ustart.get("phone"):
            await message.answer(
                "Ro'yxatdan o'tishni yakunlang 👇\nTasdiqlash uchun telefon raqamingizni yuboring:",
                reply_markup=phone_kb(norm_lang(ustart.get("language"))))
            return
        if not ustart.get("video_note"):
            await message.answer(
                "Ro'yxatdan o'tishni yakunlang 🎥\n"
                "Video-krujok yozib yuboring (haqiqiy odam ekaningizni tasdiqlash uchun).",
                reply_markup=ReplyKeyboardRemove())
            return

    kb = app_kb()
    if not kb:
        await message.answer("Ilova hozircha sozlanmagan. Birozdan keyin urinib ko'ring 🙏")
        return
    caption = (
        "💞 Luvora — xush kelibsan!\n"
        "O'zbekistonda tanishuv endi tez, qulay va zamonaviy:\n"
        "🔥 Anketalar (swipe)  💛 Match va layklar  💬 Telegram ichida suhbat\n"
        "\n"
        "💞 Добро пожаловать в Luvora!\n"
        "Знакомства по Узбекистану — быстро, удобно и современно:\n"
        "🔥 Анкеты (свайп)  💛 Мэтчи и лайки  💬 Общение прямо в Telegram\n"
        "\n"
        "👇 Boshlash / Начать"
    )
    base = os.path.dirname(os.path.abspath(__file__))
    img = os.path.join(base, "logo.png")           # o'z logong (bo'lsa)
    if not os.path.exists(img):
        img = os.path.join(base, "welcome.png")     # zaxira banner
    try:
        if os.path.exists(img):
            await message.answer_photo(FSInputFile(img), caption=caption, reply_markup=kb)
        else:
            await message.answer(caption, reply_markup=kb)
    except Exception:
        await message.answer(caption, reply_markup=kb)

    # 🎁 Referal taklifi — foydalanuvchi ro'yxatdan o'tgan tilida
    user = get_user(uid)
    lng = norm_lang(user.get("language")) if user else "uz"
    cnt = user.get("ref_count", 0) if user else 0
    if BOT_USERNAME:
        link = f"https://t.me/{BOT_USERNAME}?start=ref{uid}"
        ref_txt = {
            "uz": (f"🎁 5 ta do'stingizni taklif qiling — 1 oylik Premium sovg'a! 👑\n\n"
                   f"Sizning havolangiz:\n{link}\n\n"
                   f"Taklif qilinganlar: {cnt % 5}/5" + (f"  (jami {cnt})" if cnt else "")),
            "ru": (f"🎁 Пригласите 5 друзей — Premium на 1 месяц в подарок! 👑\n\n"
                   f"Ваша ссылка:\n{link}\n\n"
                   f"Приглашено: {cnt % 5}/5" + (f"  (всего {cnt})" if cnt else "")),
        }[lng]
        # eski 1/2/3/4 klaviaturani tozalaymiz
        await message.answer(ref_txt, reply_markup=ReplyKeyboardRemove())


# ============================== BUYRUQLAR =================================

@dp.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return
    await state.set_state(Admin.menu)
    await message.answer("👑 Admin panel", reply_markup=admin_kb())


@dp.message(Command("pro"))
async def cmd_pro(message: Message, state: FSMContext):
    """Admin uchun: o'ziga Premium + doimiy Boost berish (yoki bekor qilish)."""
    if message.from_user.id not in ADMINS:
        return
    p = get_user(message.from_user.id)
    if not p:
        await message.answer("Avval /start bilan anketa yarating.")
        return
    if p.get("premium"):
        p["premium"] = False
        p["boost_until"] = 0
        save_db()
        await message.answer("Premium o'chirildi.")
    else:
        import time as _t
        p["premium"] = True
        p["boost_until"] = int(_t.time() * 1000) + 10 * 365 * 24 * 3600 * 1000  # ~10 yil
        save_db()
        await message.answer("👑 Sizga Premium berildi va anketangiz doimiy BOOST'да — "
                             "endi hammaga birinchi (tepada) ko'rinadi.")


@dp.pre_checkout_query()
async def process_pre_checkout(q: PreCheckoutQuery):
    # Stars to'lovini tasdiqlaymiz
    try:
        await q.answer(ok=True)
    except Exception:
        pass


@dp.message(F.successful_payment)
async def process_successful_payment(message: Message):
    sp = message.successful_payment
    payload = sp.invoice_payload or ""

    # --- Virtual sovg'a ---
    if payload.startswith("gift:"):
        try:
            _, gift, target = payload.split(":")
        except ValueError:
            return
        g = GIFTS.get(gift)
        tgt = get_user(target)
        sender_id = str(message.from_user.id)
        sender = get_user(sender_id)
        if g and tgt:
            tgt.setdefault("likes_incoming", []).append({
                "from": sender_id, "gift_emoji": g["emoji"], "gift_name": g["name"],
                "super": True, "date": today(),
            })
            save_db()
            sname = sender.get("name", "Kimdir") if sender else "Kimdir"
            try:
                await bot.send_message(int(target), f"{g['emoji']} {sname} sizga «{g['name']}» sovg'a qildi!",
                                       reply_markup=app_kb())
            except Exception:
                pass
        await message.answer(f"{g['emoji'] if g else '🎁'} Sovg'a yuborildi!")
        return

    # --- Premium / Boost ---
    try:
        uid, product = payload.split(":")
    except ValueError:
        return
    p = get_user(uid)
    prod = STAR_PRODUCTS.get(product)
    if not p or not prod:
        return
    import time as _t
    now = int(_t.time() * 1000)
    if prod["kind"] == "premium":
        base = max(now, int(p.get("premium_until", 0) or 0))
        p["premium_until"] = base + prod["days"] * 86400 * 1000
        p["boost_until"] = p["premium_until"]        # Premium = boost ham
        save_db()
        await message.answer(
            f"👑 Premium faollashди — {prod['days']} kun!\n"
            f"Cheksiz layk, lentada ustuvorlik va boshqa imkoniyatlar ochildi. "
            f"Obuna muddати avtomatik tekshirilib turadi.",
            reply_markup=app_kb(),
        )
    else:
        base = max(now, int(p.get("boost_until", 0) or 0))
        p["boost_until"] = base + prod["hours"] * 3600 * 1000
        save_db()
        await message.answer(f"🚀 Boost faollashди — {prod['hours']} soat! Anketangiz tepada.",
                             reply_markup=app_kb())


@dp.message(Command("givepro"))
async def cmd_givepro(message: Message, command: CommandObject):
    """Admin: /givepro <user_id> [kun=30] — foydalanuvchiga Premium beradi (karta orqali to'lovdan keyin)."""
    if message.from_user.id not in ADMINS:
        return
    args = (command.args or "").split()
    if not args:
        await message.answer("Foydalanish: /givepro <user_id> [kun]\nMasalan: /givepro 123456789 30")
        return
    uid = args[0]
    days = int(args[1]) if len(args) > 1 and args[1].isdigit() else 30
    p = get_user(uid)
    if not p:
        await message.answer("Foydalanuvchi topilmadi. U avval ilovada ro'yxatdan o'tsin.")
        return
    import time as _t
    now = int(_t.time() * 1000)
    base = max(now, int(p.get("premium_until", 0) or 0))
    p["premium_until"] = base + days * 86400 * 1000
    p["boost_until"] = p["premium_until"]
    save_db()
    await message.answer(f"✅ {uid} ({p.get('name','')}) ga {days} kun Premium berildi.")
    try:
        await bot.send_message(int(uid), f"👑 Sizga {days} kun Premium berildi! Rahmat. Ilovani oching 👇",
                               reply_markup=app_kb())
    except Exception:
        pass


@dp.message(Command("likes"))
async def cmd_likes(message: Message, state: FSMContext):
    p = get_user(message.from_user.id)
    if not p or not p.get("registered"):
        await message.answer(t("fill_first", await ulng(message, state)))
        return
    await show_next_like(message.chat.id, message.from_user.id, state)


# ============================== RO'YXATDAN O'TISH =========================

@dp.message(Reg.language, F.text.in_(LANGUAGES))
async def reg_language(message: Message, state: FSMContext):
    await state.update_data(language=message.text)
    lng = norm_lang(message.text)
    await state.set_state(Reg.start)
    # Salomlashuv — IKKI TILDA (start bosishdan oldin)
    await message.answer(WELCOME_BILINGUAL, reply_markup=start_kb(lng))


@dp.message(Reg.language)
async def reg_language_wrong(message: Message):
    await message.answer(TEXTS["lang_wrong"]["uz"] + "\n" + TEXTS["lang_wrong"]["ru"],
                         reply_markup=lang_kb())


@dp.message(Reg.start, F.text.in_(B_START))
async def reg_start(message: Message, state: FSMContext):
    lng = await ulng(message, state)
    await state.set_state(Reg.agree)
    await message.answer(t("agree", lng), reply_markup=agree_kb())


@dp.message(Reg.agree, F.text == "👌 Ok")
async def reg_agree(message: Message, state: FSMContext):
    lng = await ulng(message, state)
    await state.set_state(Reg.age)
    await message.answer(t("age_q", lng), reply_markup=age_kb())


@dp.message(Reg.age)
async def reg_age(message: Message, state: FSMContext):
    lng = await ulng(message, state)
    text = (message.text or "").strip()
    if not text.isdigit() or not (14 <= int(text) <= 99):
        await message.answer(t("age_wrong", lng), reply_markup=age_kb())
        return
    await state.update_data(age=int(text))
    await state.set_state(Reg.gender)
    await message.answer(t("gender_q", lng), reply_markup=gender_kb(lng))


@dp.message(Reg.gender, F.text.in_(B_GENDER))
async def reg_gender(message: Message, state: FSMContext):
    lng = await ulng(message, state)
    gender = "qiz" if message.text in B_GENDER_F else "yigit"
    await state.update_data(gender=gender)
    await state.set_state(Reg.interest)
    await message.answer(t("interest_q", lng), reply_markup=interest_kb(lng))


@dp.message(Reg.interest, F.text.in_(B_INTEREST))
async def reg_interest(message: Message, state: FSMContext):
    lng = await ulng(message, state)
    await state.update_data(interest=INTEREST_MAP.get(message.text, "Farqi yo'q"))
    await state.set_state(Reg.city)
    await message.answer(t("city_q", lng), reply_markup=city_kb(lng))


@dp.message(Reg.city, F.location)
async def reg_city_location(message: Message, state: FSMContext):
    lng = await ulng(message, state)
    lat = message.location.latitude
    lon = message.location.longitude
    city = await reverse_geocode(lat, lon, lng)
    await state.update_data(lat=lat, lon=lon, city=city)
    if not city:
        await message.answer(t("city_notfound", lng))
        return
    await ask_name(message, state)


@dp.message(Reg.city, F.text)
async def reg_city_text(message: Message, state: FSMContext):
    await state.update_data(city=message.text.strip())
    await ask_name(message, state)


async def ask_name(message: Message, state: FSMContext):
    lng = await ulng(message, state)
    await state.set_state(Reg.name)
    tg_name = message.from_user.first_name or ""
    await message.answer(t("name_q", lng), reply_markup=name_kb(tg_name))


@dp.message(Reg.name, F.text)
async def reg_name(message: Message, state: FSMContext):
    lng = await ulng(message, state)
    await state.update_data(name=message.text.strip())
    await state.set_state(Reg.about)
    await message.answer(t("about_q", lng), reply_markup=about_kb(lng))


@dp.message(Reg.about, F.text)
async def reg_about(message: Message, state: FSMContext):
    lng = await ulng(message, state)
    about = "" if message.text in B_SKIP else message.text.strip()
    await state.update_data(about=about, media=[])
    await state.set_state(Reg.photo)
    await message.answer(t("photo_q", lng), reply_markup=ReplyKeyboardRemove())


@dp.message(Reg.photo, F.photo)
async def reg_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    media = data.get("media", [])
    media.append({"type": "photo", "file_id": message.photo[-1].file_id})
    await _after_media(message, state, media)


@dp.message(Reg.photo, F.video)
async def reg_video(message: Message, state: FSMContext):
    data = await state.get_data()
    media = data.get("media", [])
    media.append({"type": "video", "file_id": message.video.file_id})
    await _after_media(message, state, media)


async def _after_media(message: Message, state: FSMContext, media):
    lng = await ulng(message, state)
    await state.update_data(media=media)
    n = len(media)
    if n >= MAX_MEDIA:
        await message.answer(t("media_added_max", lng, n=n, mx=MAX_MEDIA))
        await ask_phone(message, state)
    else:
        await message.answer(t("media_added_more", lng, n=n, mx=MAX_MEDIA),
                             reply_markup=save_photo_kb(lng))


@dp.message(Reg.photo, F.text.in_(B_SAVE_PHOTO))
async def reg_photo_done(message: Message, state: FSMContext):
    lng = await ulng(message, state)
    data = await state.get_data()
    if not data.get("media"):
        await message.answer(t("need_one_media", lng))
        return
    await ask_phone(message, state)


@dp.message(Reg.photo)
async def reg_photo_wrong(message: Message, state: FSMContext):
    await message.answer(t("send_photo_wrong", await ulng(message, state)))


async def ask_phone(message: Message, state: FSMContext):
    lng = await ulng(message, state)
    await state.set_state(Reg.phone)
    await message.answer(t("phone_q", lng), reply_markup=phone_kb(lng))


@dp.message(Reg.phone, F.contact)
async def reg_phone(message: Message, state: FSMContext):
    lng = await ulng(message, state)
    await state.update_data(phone=message.contact.phone_number)
    await state.set_state(Reg.verify)
    await message.answer(t("verify_q", lng), reply_markup=ReplyKeyboardRemove())


@dp.message(Reg.phone)
async def reg_phone_wrong(message: Message, state: FSMContext):
    lng = await ulng(message, state)
    await message.answer(t("phone_wrong", lng), reply_markup=phone_kb(lng))


@dp.message(Reg.verify, F.video_note)
async def reg_verify(message: Message, state: FSMContext):
    await state.update_data(video_note=message.video_note.file_id)
    await finalize_and_confirm(message, state)


@dp.message(Reg.verify)
async def reg_verify_wrong(message: Message, state: FSMContext):
    await message.answer(t("verify_wrong", await ulng(message, state)))


async def finalize_and_confirm(message: Message, state: FSMContext):
    lng = await ulng(message, state)
    data = await state.get_data()
    caption = f"{data['name']}, {data['age']}, {data.get('city', '')}"
    if data.get("about"):
        caption += f"\n\n{data['about']}"
    await state.set_state(Reg.confirm)
    await message.answer(t("profile_preview", lng))
    await send_media(message.chat.id, data.get("media", []), caption=caption)
    await message.answer(t("all_correct", lng), reply_markup=confirm_kb(lng))


@dp.message(Reg.confirm, F.text.in_(B_YES))
async def reg_confirm_yes(message: Message, state: FSMContext):
    data = await state.get_data()
    uid = message.from_user.id
    prof = get_user(uid) or {}
    prof.update({
        "id": str(uid),
        "username": message.from_user.username,
        "language": data.get("language"),
        "age": data.get("age"),
        "gender": data.get("gender"),
        "interest": data.get("interest"),
        "city": data.get("city", ""),
        "lat": data.get("lat"),
        "lon": data.get("lon"),
        "name": data.get("name"),
        "about": data.get("about", ""),
        "media": data.get("media", []),
        "phone": data.get("phone"),
        "video_note": data.get("video_note"),
        "registered": True,
        "approved": False,   # admin tasdiqlaguncha ko'rinmaydi
    })
    prof.setdefault("seen", [])
    prof.setdefault("likes_incoming", [])
    prof.setdefault("created", today())
    prof.setdefault("banned", False)
    prof.setdefault("hidden", False)
    prof.setdefault("ref_count", 0)

    ref_by = data.get("ref_by")
    if ref_by and not prof.get("ref_credited") and ref_by != str(uid):
        referrer = get_user(ref_by)
        if referrer:
            referrer["ref_count"] = referrer.get("ref_count", 0) + 1
            prof["ref_credited"] = True
            prof["ref_by"] = ref_by
            try:
                await bot.send_message(int(ref_by), t("ref_credited", norm_lang(referrer.get("language"))))
            except Exception:
                pass

    db["users"][str(uid)] = prof
    save_db()

    lng = norm_lang(prof.get("language"))
    await state.clear()
    await message.answer(t("pending_user", lng), reply_markup=ReplyKeyboardRemove())
    await send_to_moderation(uid, prof)


@dp.message(Reg.confirm, F.text.in_(B_CHANGE))
async def reg_confirm_no(message: Message, state: FSMContext):
    lng = await ulng(message, state)
    await state.set_state(Reg.age)
    await state.update_data(age=None, gender=None, interest=None, city=None,
                            lat=None, lon=None, name=None, about=None, media=[],
                            phone=None, video_note=None)
    await message.answer(t("refill_age", lng), reply_markup=age_kb())


# ============================== ANKETALARNI KO'RISH =======================

@dp.message(Browse.viewing, F.text == "❤️")
async def like_profile(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data.get("current")
    if target_id:
        await record_like(message.from_user.id, target_id)
    await show_next_profile(message.chat.id, message.from_user.id, state)


@dp.message(Browse.viewing, F.text == "👎")
async def dislike_profile(message: Message, state: FSMContext):
    await show_next_profile(message.chat.id, message.from_user.id, state)


@dp.message(Browse.viewing, F.text == "💌/📹")
async def message_profile(message: Message, state: FSMContext):
    lng = user_lng(message.from_user.id)
    await state.set_state(Browse.messaging)
    await message.answer(t("write_msg", lng), reply_markup=back_kb(lng))


@dp.message(Browse.viewing, F.text == "💤")
async def sleep_profile(message: Message, state: FSMContext):
    await show_sleep_menu(message.chat.id, state)


@dp.message(Browse.viewing)
async def viewing_other(message: Message):
    await message.answer(t("use_buttons", user_lng(message.from_user.id)), reply_markup=browse_kb())


# --- yoqqan odamga xabar yozish ---

@dp.message(Browse.messaging, F.text.in_(B_BACK))
async def messaging_back(message: Message, state: FSMContext):
    data = await state.get_data()
    tid = data.get("current")
    target = get_user(tid) if tid else None
    if target:
        user = get_user(message.from_user.id)
        await state.set_state(Browse.viewing)
        await message.answer("✨🔍", reply_markup=browse_kb())
        caption = f"{target['name']}, {target['age']}, {location_str(user, target)}"
        if target.get("about"):
            caption += f"\n\n{target['about']}"
        await send_media(message.chat.id, target.get("media", []), caption=caption)
    else:
        await show_next_profile(message.chat.id, message.from_user.id, state)


@dp.message(Browse.messaging)
async def messaging_send(message: Message, state: FSMContext):
    data = await state.get_data()
    tid = data.get("current")
    text = message.text
    media = None
    if message.photo:
        media = {"type": "photo", "file_id": message.photo[-1].file_id}
        text = message.caption
    elif message.video:
        media = {"type": "video", "file_id": message.video.file_id}
        text = message.caption
    if tid:
        await record_like(message.from_user.id, tid, text=text, media=media)
    await message.answer(t("like_sent", user_lng(message.from_user.id)))
    await show_next_profile(message.chat.id, message.from_user.id, state)


# ============================== "UXLASH" MENYUSI (1/2/3/4) ================

@dp.message(Browse.menu, F.text == "1 🚀")
async def menu_browse(message: Message, state: FSMContext):
    await show_next_profile(message.chat.id, message.from_user.id, state)


@dp.message(Browse.menu, F.text == "2")
async def menu_my_profile(message: Message, state: FSMContext):
    await show_my_profile(message.chat.id, message.from_user.id, state)


@dp.message(Browse.menu, F.text == "3")
async def menu_hide(message: Message, state: FSMContext):
    lng = user_lng(message.from_user.id)
    p = get_user(message.from_user.id)
    if p:
        p["hidden"] = True
        save_db()
    await state.set_state(Browse.hidden)
    await message.answer(t("hidden_msg", lng), reply_markup=hidden_kb(lng))


@dp.message(Browse.menu, F.text == "4")
async def menu_invite(message: Message, state: FSMContext):
    lng = user_lng(message.from_user.id)
    p = get_user(message.from_user.id)
    cnt = p.get("ref_count", 0) if p else 0
    link = f"https://t.me/{BOT_USERNAME}?start=ref{message.from_user.id}"
    await message.answer(t("invite", lng, link=link, cnt=cnt), reply_markup=sleep_kb())


@dp.message(Browse.menu)
async def menu_other(message: Message):
    await message.answer(t("choose_item", user_lng(message.from_user.id)), reply_markup=sleep_kb())


@dp.message(Command("invite"))
async def cmd_invite(message: Message):
    import urllib.parse as _up
    uid = message.from_user.id
    p = get_user(uid)
    lng = norm_lang(p.get("language")) if p else "uz"
    cnt = p.get("ref_count", 0) if p else 0
    left = 5 - (cnt % 5)
    link = f"https://t.me/{BOT_USERNAME}?start=ref{uid}"
    share_text = {"uz": "Luvora — yangi tanishuvlar shu yerda! Menga qo'shil 💞",
                  "ru": "Luvora — новые знакомства здесь! Присоединяйся 💞"}[lng]
    share_url = "https://t.me/share/url?url=" + _up.quote(link) + "&text=" + _up.quote(share_text)
    txt = {
        "uz": (f"🎁 Do'st taklif qiling — har 5 ta do'st uchun 1 oy Premium 👑!\n\n"
               f"🔗 Sizning havolangiz:\n{link}\n\n"
               f"👥 Taklif qilinganlar: {cnt} ta\n"
               f"⏳ Keyingi sovg'agacha: {left} ta qoldi"),
        "ru": (f"🎁 Приглашайте друзей — за каждые 5 друзей 1 месяц Premium 👑!\n\n"
               f"🔗 Ваша ссылка:\n{link}\n\n"
               f"👥 Приглашено: {cnt} чел.\n"
               f"⏳ До следующего подарка: осталось {left}"),
    }[lng]
    btn = {"uz": "📤 Do'stlarga ulashish", "ru": "📤 Поделиться с друзьями"}[lng]
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=btn, url=share_url)]])
    await message.answer(txt, reply_markup=kb, disable_web_page_preview=True)


@dp.message(Command("autopost"))
async def cmd_autopost(message: Message):
    if message.from_user.id not in ADMINS:
        return
    await do_daily_channel_post()
    await message.answer("✅ Kanalga navbatdagi avtopost joylandi (test).")


@dp.message(Command("seedoff"))
async def cmd_seedoff(message: Message):
    if message.from_user.id not in ADMINS:
        return
    ids = [k for k in list(db["users"].keys()) if k.startswith("demo_s")]
    for k in ids:
        db["users"].pop(k, None)
    save_db()
    await message.answer(f"🗑 {len(ids)} ta soxta (seed) anketa o'chirildi.")


@dp.message(Command("seedon"))
async def cmd_seedon(message: Message):
    if message.from_user.id not in ADMINS:
        return
    seed_bot_profiles(300)
    db["seeded_v1"] = True
    save_db()
    cnt = sum(1 for k in db["users"] if k.startswith("demo_s"))
    await message.answer(f"✅ Soxta anketalar tiklandi. Hozir jami: {cnt} ta.")


# --- yashirilgan anketa ---

@dp.message(Browse.hidden, F.text.in_(B_HIDDEN_RET))
async def unhide(message: Message, state: FSMContext):
    p = get_user(message.from_user.id)
    if p:
        p["hidden"] = False
        save_db()
    await message.answer(t("back_in_game", user_lng(message.from_user.id)))
    await show_next_profile(message.chat.id, message.from_user.id, state)


@dp.message(Browse.hidden)
async def hidden_other(message: Message):
    lng = user_lng(message.from_user.id)
    await message.answer(t("press_return", lng), reply_markup=hidden_kb(lng))


# ============================== "MENING ANKETAM" MENYUSI =================

@dp.message(Browse.my_profile, F.text == "1")
async def myp_browse(message: Message, state: FSMContext):
    await show_next_profile(message.chat.id, message.from_user.id, state)


@dp.message(Browse.my_profile, F.text == "2")
async def myp_refill(message: Message, state: FSMContext):
    lng = user_lng(message.from_user.id)
    p = get_user(message.from_user.id) or {}
    await state.set_state(Reg.age)
    await state.update_data(language=p.get("language"), media=[])
    await message.answer(t("refill_age", lng), reply_markup=age_kb())


@dp.message(Browse.my_profile, F.text == "3")
async def myp_edit_photo(message: Message, state: FSMContext):
    await state.set_state(Edit.photo)
    await state.update_data(media=[])
    await message.answer(t("photo_q", user_lng(message.from_user.id)), reply_markup=ReplyKeyboardRemove())


@dp.message(Browse.my_profile, F.text == "4")
async def myp_edit_about(message: Message, state: FSMContext):
    lng = user_lng(message.from_user.id)
    await state.set_state(Edit.about)
    await message.answer(t("about_q", lng), reply_markup=ReplyKeyboardRemove())


@dp.message(Browse.my_profile, F.text == "5 🌐")
async def myp_change_lang(message: Message, state: FSMContext):
    await state.set_state(Settings.language)
    # ikki tilda so'raymiz
    await message.answer(
        TEXTS["lang_choose"]["uz"] + "\n" + TEXTS["lang_choose"]["ru"],
        reply_markup=lang_kb(),
    )


@dp.message(Browse.my_profile)
async def myp_other(message: Message):
    await message.answer(t("choose_item", user_lng(message.from_user.id)), reply_markup=my_profile_kb())


# --- tilni o'zgartirish ---

@dp.message(Settings.language, F.text.in_(LANGUAGES))
async def settings_language_set(message: Message, state: FSMContext):
    p = get_user(message.from_user.id)
    if p:
        p["language"] = message.text
        save_db()
    lng = norm_lang(message.text)
    await message.answer(t("lang_changed", lng))
    await show_my_profile(message.chat.id, message.from_user.id, state)


@dp.message(Settings.language)
async def settings_language_wrong(message: Message):
    await message.answer(TEXTS["lang_wrong"]["uz"] + "\n" + TEXTS["lang_wrong"]["ru"],
                         reply_markup=lang_kb())


# --- fotoni tahrirlash ---

@dp.message(Edit.photo, F.photo)
async def edit_photo_add(message: Message, state: FSMContext):
    data = await state.get_data()
    media = data.get("media", [])
    media.append({"type": "photo", "file_id": message.photo[-1].file_id})
    await _edit_media_after(message, state, media)


@dp.message(Edit.photo, F.video)
async def edit_video_add(message: Message, state: FSMContext):
    data = await state.get_data()
    media = data.get("media", [])
    media.append({"type": "video", "file_id": message.video.file_id})
    await _edit_media_after(message, state, media)


async def _edit_media_after(message: Message, state: FSMContext, media):
    lng = user_lng(message.from_user.id)
    await state.update_data(media=media)
    n = len(media)
    if n >= MAX_MEDIA:
        await _save_new_media(message, state, media)
    else:
        await message.answer(t("media_added_more", lng, n=n, mx=MAX_MEDIA),
                             reply_markup=save_photo_kb(lng))


@dp.message(Edit.photo, F.text.in_(B_SAVE_PHOTO))
async def edit_photo_done(message: Message, state: FSMContext):
    lng = user_lng(message.from_user.id)
    data = await state.get_data()
    media = data.get("media", [])
    if not media:
        await message.answer(t("need_one_media", lng))
        return
    await _save_new_media(message, state, media)


async def _save_new_media(message: Message, state: FSMContext, media):
    p = get_user(message.from_user.id)
    if p:
        p["media"] = media
        save_db()
    await message.answer(t("media_updated", user_lng(message.from_user.id)))
    await show_next_profile(message.chat.id, message.from_user.id, state)


@dp.message(Edit.photo)
async def edit_photo_other(message: Message):
    await message.answer(t("send_photo_wrong", user_lng(message.from_user.id)))


# --- matnni tahrirlash ---

@dp.message(Edit.about, F.text)
async def edit_about_save(message: Message, state: FSMContext):
    p = get_user(message.from_user.id)
    if p:
        p["about"] = message.text.strip()
        save_db()
    await message.answer(t("about_updated", user_lng(message.from_user.id)))
    await show_next_profile(message.chat.id, message.from_user.id, state)


# ============================== KELGAN LAYKLAR (/likes) ===================

async def show_next_like(chat_id, uid, state: FSMContext):
    lng = user_lng(uid)
    p = get_user(uid)
    likes = p.get("likes_incoming", [])
    if not likes:
        await bot.send_message(chat_id, t("no_likes", lng))
        await show_sleep_menu(chat_id, state)
        return

    like = likes[0]
    liker = get_user(like["from"])
    await state.set_state(Likes.viewing)
    await state.update_data(like_from=like["from"])

    if liker:
        caption = f"{liker.get('name', '—')}, {liker.get('age', '')}, {liker.get('city', '')}"
        if liker.get("about"):
            caption += f"\n\n{liker['about']}"
        await bot.send_message(chat_id, t("your_liked", lng), reply_markup=likes_kb(lng))
        await send_media(chat_id, liker.get("media", []), caption=caption)
    else:
        await bot.send_message(chat_id, t("someone_liked", lng), reply_markup=likes_kb(lng))

    if like.get("text"):
        await bot.send_message(chat_id, t("msg_label", lng, text=like["text"]))
    if like.get("media"):
        await send_media(chat_id, [like["media"]])


@dp.message(Likes.viewing, F.text.in_(B_LIKE_YES))
async def like_accept(message: Message, state: FSMContext):
    lng = user_lng(message.from_user.id)
    data = await state.get_data()
    from_id = data.get("like_from")
    me = get_user(message.from_user.id)
    liker = get_user(from_id)

    me["likes_incoming"] = [l for l in me.get("likes_incoming", []) if l["from"] != from_id]
    if liker:
        add_match(message.from_user.id, from_id)
    save_db()

    if liker:
        my_contact = f"@{me['username']}" if me.get("username") else me.get("name")
        their_contact = f"@{liker['username']}" if liker.get("username") else liker.get("name")
        await message.answer(t("mutual", lng, contact=their_contact))
        if not str(from_id).startswith("demo"):
            try:
                await bot.send_message(int(from_id),
                                       t("mutual_notify", norm_lang(liker.get("language")), contact=my_contact))
            except Exception:
                pass

    await show_next_like(message.chat.id, message.from_user.id, state)


@dp.message(Likes.viewing, F.text.in_(B_LIKE_SKIP))
async def like_skip(message: Message, state: FSMContext):
    data = await state.get_data()
    from_id = data.get("like_from")
    me = get_user(message.from_user.id)
    me["likes_incoming"] = [l for l in me.get("likes_incoming", []) if l["from"] != from_id]
    save_db()
    await show_next_like(message.chat.id, message.from_user.id, state)


@dp.message(Likes.viewing, F.text.in_(B_LIKE_BACK))
async def like_back(message: Message, state: FSMContext):
    await show_next_profile(message.chat.id, message.from_user.id, state)


@dp.message(Likes.viewing)
async def like_other(message: Message):
    lng = user_lng(message.from_user.id)
    await message.answer(t("choose_button", lng), reply_markup=likes_kb(lng))


# ============================== ADMIN PANEL ==============================

@dp.message(Admin.menu, F.text == "📊 Statistika")
async def admin_stats(message: Message):
    real = {k: v for k, v in db["users"].items() if not k.startswith("demo")}
    total = len(real)
    reg = sum(1 for v in real.values() if v.get("registered"))
    girls = sum(1 for v in real.values() if v.get("gender") == "qiz")
    guys = sum(1 for v in real.values() if v.get("gender") == "yigit")
    banned = sum(1 for v in real.values() if v.get("banned"))
    hidden = sum(1 for v in real.values() if v.get("hidden"))
    pending = sum(1 for v in real.values() if v.get("approved") is False)
    new_today = sum(1 for v in real.values() if v.get("created") == today())
    likes = sum(len(v.get("likes_incoming", [])) for v in real.values())
    premium = sum(1 for v in real.values() if is_premium(v))
    online = sum(1 for v in real.values() if is_online(v))
    matches_total = sum(len(v.get("matches", [])) for v in real.values()) // 2
    verified = sum(1 for v in real.values() if v.get("phone") and v.get("video_note"))
    subbed = sum(1 for v in real.values() if v.get("channel_sub"))
    # bu hafta yangi (7 kun)
    week_new = 0
    for v in real.values():
        try:
            d0 = datetime.strptime(v.get("created", ""), "%Y-%m-%d")
            if (datetime.now() - d0).days < 7:
                week_new += 1
        except Exception:
            pass
    # Top taklif qilganlar
    refs = [(k, v) for k, v in real.items() if v.get("ref_count", 0) > 0]
    refs.sort(key=lambda kv: kv[1].get("ref_count", 0), reverse=True)
    top = ""
    for k, v in refs[:10]:
        un = ("@" + v["username"]) if v.get("username") else v.get("name", "—")
        top += f"\n• {un} (ID {k}) — {v.get('ref_count', 0)} ta"
    top = top or "\n(hali yo'q)"
    await message.answer(
        "📊 Statistika:\n\n"
        f"👥 Jami foydalanuvchilar: {total}\n"
        f"✅ Anketa to'ldirganlar: {reg}\n"
        f"🟢 Hozir onlayn: {online}\n"
        f"⏳ Tekshiruvda: {pending}\n"
        f"🎥 Tasdiqlangan (tel+krujok): {verified}\n"
        f"👑 Premium: {premium}\n"
        f"💞 Jami matchlar: {matches_total}\n"
        f"📢 Kanalga obuna: {subbed}\n\n"
        f"👩 Qizlar: {girls}   👨 Yigitlar: {guys}\n"
        f"🆕 Bugun yangi: {new_today}   📅 Bu hafta: {week_new}\n"
        f"🙈 Yashirganlar: {hidden}   🚫 Ban: {banned}\n"
        f"💌 Kutayotgan layklar: {likes}\n\n"
        f"🎁 Top taklif qilganlar:{top}",
        reply_markup=admin_kb(),
    )


@dp.message(Admin.menu, F.text == "👥 Foydalanuvchilar")
async def admin_users(message: Message):
    real = [(k, v) for k, v in db["users"].items() if not k.startswith("demo")]
    if not real:
        await message.answer("Hozircha foydalanuvchi yo'q.", reply_markup=admin_kb())
        return
    lines = []
    for k, v in real[-20:]:
        flag = "🚫" if v.get("banned") else ("🙈" if v.get("hidden") else "✅")
        phone = v.get("phone") or "raqam yo'q"
        vn = "🎥bor" if v.get("video_note") else "video yo'q"
        lines.append(f"{flag} {k} — {v.get('name', '?')}, {v.get('age', '?')}, {v.get('city', '?')}\n"
                     f"     📱 {phone}  |  {vn}")
    await message.answer("👥 So'nggi foydalanuvchilar:\n\n" + "\n".join(lines), reply_markup=admin_kb())


@dp.message(Admin.menu, F.text == "📢 Xabar tarqatish")
async def admin_broadcast_ask(message: Message, state: FSMContext):
    await state.set_state(Admin.broadcast)
    await message.answer("Tarqatiladigan matnni yubor (yoki bekor qilish uchun /cancel):")


@dp.message(Admin.broadcast, Command("cancel"))
async def admin_broadcast_cancel(message: Message, state: FSMContext):
    await state.set_state(Admin.menu)
    await message.answer("Bekor qilindi.", reply_markup=admin_kb())


@dp.message(Admin.broadcast)
async def admin_broadcast_send(message: Message, state: FSMContext):
    text = message.text or ""
    ok, fail = 0, 0
    for k in list(db["users"].keys()):
        if k.startswith("demo"):
            continue
        try:
            await bot.send_message(int(k), text)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await state.set_state(Admin.menu)
    await message.answer(f"Xabar tarqatildi ✅\nYuborildi: {ok}, xato: {fail}", reply_markup=admin_kb())


@dp.message(Admin.menu, F.text == "🚫 Ban/Unban")
async def admin_ban_ask(message: Message, state: FSMContext):
    await state.set_state(Admin.ban)
    await message.answer("Ban/unban qilish uchun foydalanuvchi ID sini yubor (yoki /cancel):")


@dp.message(Admin.ban, Command("cancel"))
async def admin_ban_cancel(message: Message, state: FSMContext):
    await state.set_state(Admin.menu)
    await message.answer("Bekor qilindi.", reply_markup=admin_kb())


@dp.message(Admin.ban)
async def admin_ban_do(message: Message, state: FSMContext):
    uid = (message.text or "").strip()
    p = get_user(uid)
    if not p:
        await message.answer("Foydalanuvchi topilmadi. Qaytadan urin yoki /cancel.")
        return
    p["banned"] = not p.get("banned", False)
    save_db()
    status = "banlandi 🚫" if p["banned"] else "unbanlandi ✅"
    await state.set_state(Admin.menu)
    await message.answer(f"Foydalanuvchi {uid} {status}", reply_markup=admin_kb())


@dp.message(Admin.menu, F.text == "🎥 Tekshirish")
async def admin_check_ask(message: Message, state: FSMContext):
    await state.set_state(Admin.check)
    await message.answer("Foydalanuvchi raqami va video-krujogini ko'rish uchun ID sini yubor (yoki /cancel):")


@dp.message(Admin.check, Command("cancel"))
async def admin_check_cancel(message: Message, state: FSMContext):
    await state.set_state(Admin.menu)
    await message.answer("Bekor qilindi.", reply_markup=admin_kb())


@dp.message(Admin.check)
async def admin_check_do(message: Message, state: FSMContext):
    uid = (message.text or "").strip()
    p = get_user(uid)
    if not p:
        await message.answer("Foydalanuvchi topilmadi. Qaytadan urin yoki /cancel.")
        return
    phone_str = p.get('phone') or "raqam yo'q"
    lines = [
        f"🆔 {uid}",
        f"👤 {p.get('name', '?')}, {p.get('age', '?')}",
        f"🏙 {p.get('city', '?')}",
        f"📱 Telefon: {phone_str}",
    ]
    if p.get("username"):
        lines.append(f"🔗 @{p['username']}")
    await message.answer("\n".join(lines))
    if p.get("media"):
        await send_media(message.chat.id, p["media"], caption="📸 Anketa")
    if p.get("video_note"):
        await message.answer("🎥 Video-tasdiq (krujok):")
        try:
            await bot.send_video_note(message.chat.id, p["video_note"])
        except Exception:
            await message.answer("Krujokni yuborib bo'lmadi 🙈")
    else:
        await message.answer("🎥 Bu foydalanuvchi video-krujok yozmagan.")
    await state.set_state(Admin.menu)
    await message.answer("Tayyor.", reply_markup=admin_kb())


@dp.message(Admin.menu, F.text == "🔙 Chiqish")
async def admin_exit(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Admin paneldan chiqildi.", reply_markup=ReplyKeyboardRemove())
    if get_user(message.from_user.id):
        await show_next_profile(message.chat.id, message.from_user.id, state)


@dp.message(Admin.menu, F.text == "👑 Premium (Pro)")
async def admin_pro_ask(message: Message, state: FSMContext):
    await state.set_state(Admin.pro)
    await message.answer(
        "👑 Premium berish / o'chirish\n\n"
        "Foydalanuvchi ID va kunini yuboring:\n"
        "• 123456789 30  → 30 kun Premium beradi\n"
        "• 123456789 0   → Premium'ni o'chiradi\n\n"
        "(ID ni /admin → 👥 Foydalanuvchilar dan ko'rasiz. /cancel — bekor)"
    )


@dp.message(Admin.pro, Command("cancel"))
async def admin_pro_cancel(message: Message, state: FSMContext):
    await state.set_state(Admin.menu)
    await message.answer("Bekor qilindi.", reply_markup=admin_kb())


@dp.message(Admin.pro)
async def admin_pro_do(message: Message, state: FSMContext):
    parts = (message.text or "").split()
    if not parts:
        await message.answer("ID yuboring. Masalan: 123456789 30")
        return
    uid = parts[0]
    days = int(parts[1]) if len(parts) > 1 and parts[1].lstrip("-").isdigit() else 30
    p = get_user(uid)
    if not p:
        await message.answer("Foydalanuvchi topilmadi. Qaytadan urin yoki /cancel.")
        return
    import time as _t
    now = int(_t.time() * 1000)
    await state.set_state(Admin.menu)
    if days <= 0:
        p["premium"] = False
        p["premium_until"] = 0
        p["boost_until"] = 0
        save_db()
        await message.answer(f"❌ {uid} ({p.get('name','')}) — Premium o'chirildi.", reply_markup=admin_kb())
        try:
            await bot.send_message(int(uid), "Premium obunangiz o'chirildi.")
        except Exception:
            pass
    else:
        base = max(now, int(p.get("premium_until", 0) or 0))
        p["premium_until"] = base + days * 86400 * 1000
        p["boost_until"] = p["premium_until"]
        save_db()
        await message.answer(f"✅ {uid} ({p.get('name','')}) — {days} kun Premium berildi.", reply_markup=admin_kb())
        try:
            await bot.send_message(int(uid), f"👑 Sizga {days} kun Premium berildi! Ilovani oching 👇",
                                   reply_markup=app_kb())
        except Exception:
            pass


@dp.message(Admin.menu, F.text == "🗑 Anketa o'chirish")
async def admin_del_ask(message: Message, state: FSMContext):
    await state.set_state(Admin.delete)
    await message.answer(
        "🗑 Anketani butunlay o'chirish\n\n"
        "Foydalanuvchi ID sini yuboring.\n"
        "U bazadan butunlay o'chadi — layk, match, yozishmalar ham.\n"
        "Keyingi safar botga kirsa — noldan ro'yxatdan o'tadi.\n\n"
        "(ID ni 👥 Foydalanuvchilar dan ko'rasiz. /cancel — bekor)"
    )


@dp.message(Admin.delete, Command("cancel"))
async def admin_del_cancel(message: Message, state: FSMContext):
    await state.set_state(Admin.menu)
    await message.answer("Bekor qilindi.", reply_markup=admin_kb())


@dp.message(Admin.delete)
async def admin_del_do(message: Message, state: FSMContext):
    uid = (message.text or "").strip().split()[0] if (message.text or "").strip() else ""
    if not uid.isdigit():
        await message.answer("To'g'ri ID yuboring (faqat raqam). /cancel — bekor.")
        return
    p = get_user(uid)
    if not p:
        await message.answer("Bunday foydalanuvchi topilmadi. Qaytadan urin yoki /cancel.")
        return
    nm = p.get("name", "")
    purge_user(uid)
    await state.set_state(Admin.menu)
    await message.answer(f"🗑 {uid} ({nm}) — anketa butunlay o'chirildi ✅", reply_markup=admin_kb())
    try:
        await bot.send_message(int(uid), "Anketangiz o'chirildi. Qayta ro'yxatdan o'tish uchun /start bosing.")
    except Exception:
        pass


@dp.message(Admin.menu, F.text == "📌 Kanalga post")
async def admin_channel_post(message: Message):
    await message.answer("📌 Kanalga post joylanmoqda...")
    ok, info = await post_channel_promo()
    if ok:
        await message.answer(
            f"✅ Post @{CHANNEL_USERNAME} kanaliga joylandi va pin qilindi.\n"
            "Kanalga qo'shilganlar shu post orqali botni ochadi.",
            reply_markup=admin_kb())
    else:
        await message.answer(
            f"❌ Joylab bo'lmadi: {info}\n\n"
            "Tekshiring: bot kanalga ADMIN qilinganmi va 'Post joylash' + 'Xabarlarni pin qilish' huquqi bormi?",
            reply_markup=admin_kb())


@dp.message(Admin.menu)
async def admin_other(message: Message):
    await message.answer("Tugma orqali bo'limni tanla 👇", reply_markup=admin_kb())


# ============================== TASDIQLASH (telefon + krujok) =============

@dp.message(F.contact)
async def verify_contact(message: Message):
    p = get_user(message.from_user.id)
    if not p or not p.get("registered"):
        return
    if p.get("phone") and p.get("video_note"):
        return   # allaqachon tasdiqlangan
    p["phone"] = message.contact.phone_number
    save_db()
    await message.answer(
        "📱 Raqam qabul qilindi ✅\n\n"
        "Endi 🎥 video-krujok yozib yuboring — haqiqiy odam ekaningizni tasdiqlash uchun.\n\n"
        "Qanday: kiritish maydonining o'ng tomonidagi 🎤 belgisini bosing — u yumaloq kamera 🔵 ga "
        "aylanadi, keyin bosib ushlab qisqa video yozing.",
        reply_markup=ReplyKeyboardRemove(),
    )


@dp.message(F.video_note)
async def verify_krujok(message: Message):
    p = get_user(message.from_user.id)
    if not p or not p.get("registered"):
        return
    if not p.get("phone"):
        await message.answer("Avval telefon raqamingizni yuboring 👇",
                             reply_markup=phone_kb(norm_lang(p.get("language"))))
        return
    p["video_note"] = message.video_note.file_id
    p["approved"] = False   # admin tasdig'ini kutadi
    save_db()
    await send_to_moderation(str(message.from_user.id), p)
    await message.answer(
        "✅ Tasdiqlash yuborildi!\n"
        "Admin ko'rib chiqadi (odatda tez). Tasdiqlangach ilova ochiladi ⏳",
        reply_markup=ReplyKeyboardRemove(),
    )


# ============================== FALLBACK ==================================

@dp.message()
async def fallback(message: Message, state: FSMContext):
    await state.clear()   # eski holatlar (Browse.menu va h.k.) tozalanadi
    p = get_user(message.from_user.id)
    if p and p.get("registered") and p.get("approved") is False:
        await message.answer(t("pending_user", norm_lang(p.get("language"))),
                             reply_markup=ReplyKeyboardRemove())
        return
    # eski 1/2/3/4 klaviaturani olib tashlaymiz va ilovaga yo'naltiramiz
    await message.answer("Hammasi ilovada 💞 «Luvora» tugmasini yoki /start ni bosing.",
                         reply_markup=ReplyKeyboardRemove())


# ============================== ISHGA TUSHIRISH ==========================

# ============================== MINI APP (WEB) ============================

WEBAPP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "miniapp")
UPLOAD_DIR = os.path.join(WEBAPP_DIR, "uploads")


def abs_url(src) -> str:
    """Ichki '/media/..' yoki '/photo/..' manzilini to'liq https ga aylantiradi (bot yuborishi uchun)."""
    if src and src.startswith("/") and WEBAPP_URL:
        return WEBAPP_URL.rstrip("/") + src
    return src


def _load_webapp_url() -> str:
    """webapp_url.txt faylidan Mini App https manzilini o'qiydi (# bilan boshlanган qatorlar e'tiborsiz)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp_url.txt")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        return line
        except Exception:
            pass
    return ""


_TUNNEL_PROC = None


def start_cloudflared_tunnel() -> str:
    """cloudflared.exe bo'lsa, avtomatik tunnel ochib, uning https manzilini qaytaradi.
    Server (Linux/VDS) da cloudflared.exe bo'lmaydi — u holda '' qaytadi va webapp_url.txt ishlatiladi."""
    global _TUNNEL_PROC
    import subprocess, re, time as _t
    base = os.path.dirname(os.path.abspath(__file__))
    exe = os.path.join(base, "cloudflared.exe")
    if not os.path.exists(exe):
        return ""
    logpath = os.path.join(base, "tunnel_auto.log")
    try:
        open(logpath, "w").close()
    except Exception:
        pass
    try:
        _TUNNEL_PROC = subprocess.Popen(
            [exe, "tunnel", "--url", f"http://localhost:{WEB_PORT}", "--logfile", logpath],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        logging.warning("cloudflared ishga tushmadi: %s", e)
        return ""
    # manzil chiqishini kutamiz (maks ~30s)
    for _ in range(30):
        _t.sleep(1)
        try:
            with open(logpath, "r", encoding="utf-8", errors="ignore") as f:
                txt = f.read()
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", txt)
            if m:
                return m.group(0)
        except Exception:
            pass
    return ""


def passes_filter(user, p) -> bool:
    """Foydalanuvchining filtriga (yosh/shahar/masofa) mos keladimi?"""
    f = user.get("filter") or {}
    amin = f.get("age_min", 0) or 0
    amax = f.get("age_max", 200) or 200
    age = p.get("age")
    if age is not None:
        try:
            if not (amin <= int(age) <= amax):
                return False
        except Exception:
            pass
    city = (f.get("city") or "").strip()
    if city and city != "Barchasi" and (p.get("city") or "") != city:
        return False
    mk = f.get("max_km", 0) or 0
    if mk and user.get("lat") and p.get("lat"):
        if haversine(user["lat"], user["lon"], p["lat"], p["lon"]) > mk:
            return False
    return True


def _match(user, p, uid) -> bool:
    if not p.get("registered") or p.get("banned") or p.get("hidden"):
        return False
    if p.get("approved") is False:
        return False
    pid = str(p.get("id", ""))
    # Seed (soxta) anketa faqat RASMI bo'lsa ko'rinadi (rasm qo'shilgani sari ko'payadi)
    if pid.startswith("demo_s"):
        try:
            if not seed_has_photo(int(pid[6:])):
                return False
        except Exception:
            return False
    # Telefon + video-krujok bilan tasdiqlanmagan anketalar hech kimga ko'rinmaydi
    # (demo/seed anketalar istisno)
    elif not pid.startswith("demo"):
        if not (p.get("phone") and p.get("video_note")):
            return False
    g = norm_gender(p.get("gender"))
    interest = norm_interest(user.get("interest"))
    if interest == "Qizlar" and g != "qiz":
        return False
    if interest == "Yigitlar" and g != "yigit":
        return False
    if not passes_filter(user, p):
        return False
    return True


def feed_for(uid, limit=15):
    """Swipe uchun nomzodlar ro'yxati (seen ni belgilamaydi)."""
    user = get_user(uid)
    if not user:
        return []
    seen = set(user.get("seen", []))
    cands = [(k, p) for k, p in db["users"].items()
             if k != str(uid) and _match(user, p, uid) and k not in seen]
    if not cands:
        # aylanaga: tarixni tozalab, qaytadan
        user["seen"] = []
        save_db()
        cands = [(k, p) for k, p in db["users"].items()
                 if k != str(uid) and _match(user, p, uid)]
    def rank(it):
        k, p = it
        is_seed = 1 if str(k).startswith("demo") else 0   # real anketalar oldinda, soxta/demo keyin
        boost = 0 if is_boosted(p) else 1   # boost'dagilar tepada
        if user.get("lat") and p.get("lat"):
            d = haversine(user["lat"], user["lon"], p["lat"], p["lon"])
        else:
            d = 1e9
        return (is_seed, boost, d)
    cands.sort(key=rank)
    return cands[:limit]


def profile_json(uid, viewer=None):
    p = get_user(uid)
    if not p:
        return None
    media = p.get("media", [])
    photos = [f"/photo/{uid}/{i}" for i, m in enumerate(media) if m.get("type") == "photo"]
    dist = ""
    if viewer:
        dist = location_str(viewer, p)
    return {
        "id": str(uid),
        "name": p.get("name", "—"),
        "age": p.get("age", ""),
        "city": p.get("city", ""),
        "about": p.get("about", ""),
        "gender": norm_gender(p.get("gender")),
        "dist": dist,
        "photos": photos,
        "premium": is_premium(p),
        "boosted": is_boosted(p),
        "online": is_online(p),
    }


def validate_init_data(init_data: str):
    """Telegram WebApp initData ni tekshirish. To'g'ri bo'lsa user dict qaytaradi."""
    if not init_data:
        return None
    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=True))
    except Exception:
        return None
    recv_hash = parsed.pop("hash", None)
    if not recv_hash:
        return None
    data_check = "\n".join(f"{k}={parsed[k]}" for k in sorted(parsed))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, recv_hash):
        return None
    try:
        return json.loads(parsed.get("user", "null"))
    except Exception:
        return None


def _auth(request):
    init = request.headers.get("X-Init-Data") or request.query.get("initData", "")
    u = validate_init_data(init)
    if u:   # onlayn holat uchun faollik vaqtini yangilaymiz
        pp = get_user(str(u["id"]))
        if pp is not None:
            import time as _t
            pp["last_active"] = int(_t.time() * 1000)
    return u


def is_online(p) -> bool:
    try:
        import time as _t
        return (_t.time() * 1000 - float(p.get("last_active", 0))) < 120000   # 2 daqiqa
    except Exception:
        return False


def refill_swipes(me) -> None:
    """Layk zaxirasini vaqt o'tishi bilan asta-sekin to'ldiradi (24 soatda to'liq)."""
    cap = FREE_SWIPE_LIMIT
    now = now_ms()
    left = me.get("swipes_left")
    last = me.get("swipe_refill_ts")
    if left is None or last is None:
        me["swipes_left"] = cap
        me["swipe_refill_ts"] = now
        return
    left = int(left)
    if left >= cap:
        me["swipe_refill_ts"] = now   # to'la — vaqtni yangilaymiz
        return
    gain = int((now - int(last)) // SWIPE_REGEN_MS)
    if gain > 0:
        me["swipes_left"] = min(cap, left + gain)
        me["swipe_refill_ts"] = int(last) + gain * SWIPE_REGEN_MS
        if me["swipes_left"] >= cap:
            me["swipe_refill_ts"] = now


def swipe_wait_min(me) -> int:
    """Keyingi layk necha daqiqadan keyin tiklanadi."""
    last = int(me.get("swipe_refill_ts", now_ms()))
    ms = SWIPE_REGEN_MS - ((now_ms() - last) % SWIPE_REGEN_MS)
    return max(1, int(ms // 60000) + 1)


def account_age_days(p) -> int:
    try:
        d0 = datetime.strptime(p.get("created", ""), "%Y-%m-%d")
        return (datetime.now() - d0).days
    except Exception:
        return 0


def needs_channel_sub(p) -> bool:
    """3 kundan oshgan, hali obunasi tasdiqlanmagan foydalanuvchi kanalga obuna bo'lishi kerak."""
    if not CHANNEL_USERNAME:
        return False
    if p.get("channel_sub"):
        return False
    return account_age_days(p) >= CHANNEL_AFTER_DAYS


async def check_channel_sub(uid) -> bool:
    """Bot orqali kanalga a'zolikni tekshiradi (bot kanalda admin bo'lishi shart)."""
    try:
        m = await bot.get_chat_member(f"@{CHANNEL_USERNAME}", int(uid))
        return getattr(m, "status", None) in ("member", "administrator", "creator")
    except Exception:
        return False


ADVICE_POSTS = [
    (
        "📸 Yaxshi profil rasmi qanday bo'ladi?\n\n"
        "✅ Yuzingiz aniq ko'rinsin — yorug' joyda, tabiiy nur bilan\n"
        "✅ Tabassum qiling — samimiy tabassum ishonch uyg'otadi\n"
        "✅ 2-3 xil rasm qo'ying: yuz, to'liq bo'y, sevimli mashg'ulot\n"
        "✅ Sifatli, tiniq surat tanlang\n\n"
        "❌ Quyoshli ko'zoynak yoki niqob — yuzni yashirmang\n"
        "❌ Guruh surati — kim ekaningiz tushunarsiz bo'ladi\n"
        "❌ Filtr va photoshopni ko'paytirib yubormang\n"
        "❌ Meme yoki mashina/manzara rasmi — bu tanishuv uchun emas\n\n"
        "💛 Haqiqiy va tabiiy bo'ling — shundaylar tez match topadi!\n"
        "➖➖➖➖➖\n"
        "📸 Каким должно быть хорошее фото профиля?\n\n"
        "✅ Лицо чётко видно — при хорошем дневном свете\n"
        "✅ Улыбайтесь — искренняя улыбка вызывает доверие\n"
        "✅ Добавьте 2-3 разных фото: лицо, в полный рост, за любимым делом\n"
        "✅ Выбирайте чёткие, качественные снимки\n\n"
        "❌ Без солнцезащитных очков и масок — не прячьте лицо\n"
        "❌ Не ставьте групповое фото — непонятно, кто вы\n"
        "❌ Не переусердствуйте с фильтрами и фотошопом\n"
        "❌ Мемы, машины и пейзажи — не для знакомств\n\n"
        "💛 Будьте настоящими — такие находят пару быстрее!"
    ),
    (
        "💬 Birinchi xabarda nima yozish kerak?\n\n"
        "✅ Ismini ayting va samimiy salomlashing\n"
        "✅ Anketasidan biror narsani eslang: \"Sayohatni yaxshi ko'rarakansiz — qayerlarda bo'lgansiz?\"\n"
        "✅ Ochiq savol bering — \"ha/yo'q\" bilan tugamaydigan\n"
        "✅ Qisqa va do'stona bo'ling\n\n"
        "❌ Faqat \"Salom\" yoki \"Qalaysan?\" — bunga kam javob beriladi\n"
        "❌ Darrov shaxsiy/qo'pol savollar bermang\n"
        "❌ Ko'p xabar ketma-ket yozmang — javobni kuting\n\n"
        "💡 Misol: \"Salom, Malika! Profilingda gitara ko'rdim 🎸 Qancha vaqtdan beri chalasan?\"\n"
        "➖➖➖➖➖\n"
        "💬 Что написать в первом сообщении?\n\n"
        "✅ Представьтесь и поздоровайтесь искренне\n"
        "✅ Упомяните что-то из анкеты: \"Вижу, вы любите путешествия — где успели побывать?\"\n"
        "✅ Задайте открытый вопрос — не на \"да/нет\"\n"
        "✅ Будьте краткими и дружелюбными\n\n"
        "❌ Просто \"Привет\" или \"Как дела?\" — на это редко отвечают\n"
        "❌ Не задавайте сразу личных и грубых вопросов\n"
        "❌ Не пишите много сообщений подряд — дождитесь ответа\n\n"
        "💡 Пример: \"Привет, Малика! Увидел гитару в профиле 🎸 Давно играешь?\""
    ),
    (
        "🛡 Xavfsiz uchrashuv qoidalari\n\n"
        "✅ Birinchi uchrashuvni ochiq, gavjum joyda belgilang (kafe, park)\n"
        "✅ Yaqin do'st yoki oilangizga qayerga borayotganingizni ayting\n"
        "✅ O'z transportingiz yoki taksida boring-keling\n"
        "✅ Ichimlik/ovqatingizni nazoratda tuting\n"
        "✅ O'zingizni noqulay his qilsangiz — ketishga haqlisiz\n\n"
        "❌ Birinchi uchrashuvda uy yoki xilvat joyga bormang\n"
        "❌ Pul so'ragan yoki karta raqami so'ragan odamga ishonmang — bu firibgarlik!\n"
        "❌ Shaxsiy ma'lumot (uy manzili, hujjat) darrov bermang\n\n"
        "⚠️ Shubhali xatti-harakat bo'lsa — anketaga shikoyat qiling. Xavfsizligingiz birinchi o'rinda!\n"
        "➖➖➖➖➖\n"
        "🛡 Правила безопасных встреч\n\n"
        "✅ Назначайте первую встречу в открытом людном месте (кафе, парк)\n"
        "✅ Скажите близкому другу или семье, куда идёте\n"
        "✅ Добирайтесь на своём транспорте или такси\n"
        "✅ Держите свой напиток/еду под контролем\n"
        "✅ Чувствуете дискомфорт — вы вправе уйти\n\n"
        "❌ Не ходите на первую встречу домой или в уединённое место\n"
        "❌ Не верьте тем, кто просит деньги или номер карты — это мошенники!\n"
        "❌ Не давайте сразу личные данные (адрес, документы)\n\n"
        "⚠️ Заметили подозрительное поведение — пожалуйтесь на анкету. Ваша безопасность превыше всего!"
    ),
]


async def post_channel_advice():
    """Kanalga 3 ta maslahat-postini joylaydi."""
    if not CHANNEL_USERNAME:
        return False, "Kanal sozlanmagan"
    chat = f"@{CHANNEL_USERNAME}"
    try:
        for txt in ADVICE_POSTS:
            await bot.send_message(chat, txt, disable_web_page_preview=True)
            await asyncio.sleep(1)
        return True, "OK"
    except Exception as e:
        return False, str(e)


# ---- Avtomatik kanal kontenti ----
AUTO_TIPS = [
    "💡 Maslahat: Anketangizni 100% to'ldiring — to'liq anketalar 3 barobar ko'p layk oladi!\n➖➖➖\n💡 Совет: Заполните анкету на 100% — полные анкеты получают в 3 раза больше лайков!",
    "💡 Maslahat: Har kuni kiring — faol foydalanuvchilar lentada yuqorida chiqadi.\n➖➖➖\n💡 Совет: Заходите каждый день — активные пользователи выше в ленте.",
    "💡 Maslahat: Suhbatni savol bilan boshlang — bu javob olish ehtimolini oshiradi.\n➖➖➖\n💡 Совет: Начинайте разговор с вопроса — так больше шансов получить ответ.",
    "💡 Maslahat: O'zingiz haqingizda qisqa, samimiy yozing — hazil ham yordam beradi 😄\n➖➖➖\n💡 Совет: Пишите о себе коротко и искренне — юмор тоже помогает 😄",
    "👑 Premium bilan: cheksiz layk, kim sizni yoqtirgani, lentada ustuvorlik. Profil → Premium.\n➖➖➖\n👑 С Premium: безлимитные лайки, кто вас лайкнул, приоритет в ленте. Профиль → Premium.",
]
AUTO_POLLS = [
    ("Birinchi uchrashuvni qayerda o'tkazasiz? / Где провести первое свидание?",
     ["☕ Kafe / Кафе", "🎬 Kino / Кино", "🌳 Sayr / Прогулка", "🍽 Restoran / Ресторан"]),
    ("Tanishuvda eng muhim sifat? / Главное качество при знакомстве?",
     ["😊 Muomala / Характер", "😄 Hazil / Юмор", "🎯 Maqsad / Цели", "❤️ Sadoqat / Верность"]),
    ("Kim birinchi yozishi kerak? / Кто должен написать первым?",
     ["👨 Yigit / Парень", "👩 Qiz / Девушка", "🤷 Farqi yo'q / Без разницы"]),
]


async def do_daily_channel_post():
    """Navbat bilan: maslahat → so'rovnoma → statistika."""
    if not (CHANNEL_USERNAME and AUTO_POST_ENABLED):
        return
    chat = f"@{CHANNEL_USERNAME}"
    idx = int(db.get("auto_idx", 0))
    kind = idx % 3
    try:
        if kind == 0:
            tip = AUTO_TIPS[(idx // 3) % len(AUTO_TIPS)]
            await bot.send_message(chat, tip, disable_web_page_preview=True)
        elif kind == 1:
            q, opts = AUTO_POLLS[(idx // 3) % len(AUTO_POLLS)]
            await bot.send_poll(chat, question=q, options=opts, is_anonymous=True)
        else:
            real = {k: v for k, v in db["users"].items() if not k.startswith("demo")}
            total = len(real)
            new_today = sum(1 for v in real.values() if v.get("created") == today())
            matches_total = sum(len(v.get("matches", [])) for v in real.values()) // 2
            await bot.send_message(
                chat,
                f"📊 Luvora bugun:\n\n👥 Jami a'zolar: {total}\n🆕 Bugun qo'shildi: {new_today}\n💞 Jami tanishuvlar: {matches_total}\n\n"
                f"Sen ham qo'shil 👇 https://t.me/{BOT_USERNAME}",
                disable_web_page_preview=True,
            )
        db["auto_idx"] = idx + 1
        save_db()
    except Exception as e:
        logging.warning("Avtopost xato: %s", e)


async def channel_autopost_loop():
    """Har kuni belgilangan soatda kanalga bitta post joylaydi."""
    from datetime import timedelta
    while True:
        try:
            now = datetime.now()
            target = now.replace(hour=AUTO_POST_HOUR, minute=0, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)
            await asyncio.sleep(max(30, (target - now).total_seconds()))
            if db.get("last_auto_date") != today():
                await do_daily_channel_post()
                db["last_auto_date"] = today()
                save_db()
        except Exception as e:
            logging.warning("Autopost loop xato: %s", e)
            await asyncio.sleep(3600)


async def post_channel_promo():
    """Kanalga botga olib boradigan tugmali post joylab, uni pin qiladi."""
    if not CHANNEL_USERNAME:
        return False, "Kanal sozlanmagan"
    chat = f"@{CHANNEL_USERNAME}"
    link = f"https://t.me/{BOT_USERNAME}?start=channel" if BOT_USERNAME else CHANNEL_URL
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💞 Luvora'ni ochish", url=link)
    ]])
    caption = (
        "💞 Luvora — yangi tanishuvlar shu yerda!\n\n"
        "• Anketa yarating va layk bosing\n"
        "• O'zaro layk — bir-biringizga yozing\n"
        "• Onlayn holat, sovg'alar, Premium\n\n"
        "Boshlash uchun pastdagi tugmani bosing 👇\n"
        "💞 Luvora — здесь новые знакомства! Нажмите кнопку ниже 👇"
    )
    try:
        logo = "logo.png" if os.path.exists("logo.png") else ("welcome.png" if os.path.exists("welcome.png") else None)
        if logo:
            msg = await bot.send_photo(chat, FSInputFile(logo), caption=caption, reply_markup=kb)
        else:
            msg = await bot.send_message(chat, caption, reply_markup=kb)
        try:
            await bot.pin_chat_message(chat, msg.message_id, disable_notification=True)
        except Exception:
            pass
        return True, "OK"
    except Exception as e:
        return False, str(e)


def _json(data, status=200):
    return web.json_response(data, status=status)


# ---- Web handlerlar ----

async def h_index(request):
    path = os.path.join(WEBAPP_DIR, "index.html")
    if not os.path.exists(path):
        return web.Response(text="Mini App fayli topilmadi (miniapp/index.html).", status=404)
    return web.FileResponse(path, headers={"Cache-Control": "no-store, must-revalidate"})


async def h_photo(request):
    uid = request.match_info["uid"]
    idx = int(request.match_info["idx"])
    p = get_user(uid)
    if not p:
        return web.Response(status=404)
    media = p.get("media", [])
    if idx >= len(media):
        return web.Response(status=404)
    m = media[idx]
    if m.get("url"):
        raise web.HTTPFound(m["url"])
    fid = m.get("file_id")
    if not fid:
        return web.Response(status=404)
    try:
        f = await bot.get_file(fid)
        buf = await bot.download_file(f.file_path)
        data = buf.read() if hasattr(buf, "read") else buf
        ctype = "image/jpeg" if m.get("type") == "photo" else "video/mp4"
        return web.Response(body=data, content_type=ctype,
                            headers={"Cache-Control": "public, max-age=86400"})
    except Exception:
        return web.Response(status=404)


async def h_me(request):
    u = _auth(request)
    if not u:
        return _json({"error": "auth"}, 401)
    uid = str(u["id"])
    p = get_user(uid)
    registered = bool(p and p.get("registered"))
    approved = bool(p and p.get("approved") is not False)
    me = profile_json(uid, p) if registered else None
    if me and p:
        me["media_raw"] = p.get("media", [])
        for k in ("height", "pref_age_min", "pref_age_max", "interests", "goal",
                  "pets", "habits", "sport", "education", "family", "comm"):
            me[k] = p.get(k)
    likes_cnt = len(p.get("likes_incoming", [])) if p else 0
    matches_cnt = len(p.get("matches", [])) if p else 0
    days = 0
    if p and p.get("created"):
        try:
            d0 = datetime.strptime(p["created"], "%Y-%m-%d")
            days = (datetime.now() - d0).days + 1
        except Exception:
            days = 1
    return _json({
        "registered": registered,
        "approved": approved,
        "me": me,
        "likes": likes_cnt,
        "matches": matches_cnt,
        "days": days,
        "visible": bool(p and not p.get("hidden")) if p else False,
        "premium": is_premium(p) if p else False,
        "premium_until": (p.get("premium_until", 0) if p else 0),
        "verified": bool(p and p.get("phone") and p.get("video_note")) if p else False,
        "lng": norm_lang(p.get("language")) if p else "uz",
        "ref_count": (p.get("ref_count", 0) if p else 0),
        "invite_link": (f"https://t.me/{BOT_USERNAME}?start=ref{uid}" if BOT_USERNAME else ""),
    })


async def h_feed(request):
    u = _auth(request)
    if not u:
        return _json({"error": "auth"}, 401)
    uid = str(u["id"])
    me = get_user(uid)
    if not me or not me.get("registered"):
        return _json({"items": [], "need_reg": True})
    if not me.get("phone") or not me.get("video_note"):
        return _json({"items": [], "need_verify": True})   # telefon+krujok tasdiqlanmagan
    if me.get("approved") is False:
        return _json({"items": [], "pending": True})
    if needs_channel_sub(me):
        # avtomatik bir marta tekshiramiz (agar allaqachon obuna bo'lgan bo'lsa — o'tkazamiz)
        if await check_channel_sub(uid):
            me["channel_sub"] = True
            save_db()
        else:
            return _json({"items": [], "need_sub": True, "channel": CHANNEL_URL})
    items = [profile_json(k, me) for k, _ in feed_for(uid)]
    return _json({"items": items})


async def h_act(request):
    u = _auth(request)
    if not u:
        return _json({"error": "auth"}, 401)
    uid = str(u["id"])
    body = await request.json()
    target = str(body.get("target", ""))
    action = body.get("action")
    text = body.get("text")
    me = get_user(uid)
    if not me:
        return _json({"error": "no_user"}, 400)
    # Bepul limit: 24 soatda 100 ta layk+dislayk zaxirasi, asta-sekin tiklanadi. Premium — cheksiz.
    counted = action in ("like", "super", "pass")
    if counted and not is_premium(me):
        refill_swipes(me)
        if int(me.get("swipes_left", 0)) <= 0:
            save_db()
            return _json({"ok": False, "limit": True, "left": 0,
                          "cap": FREE_SWIPE_LIMIT, "wait_min": swipe_wait_min(me)})
        me["swipes_left"] = int(me["swipes_left"]) - 1
    me.setdefault("seen", [])
    if target and target not in me["seen"]:
        me["seen"].append(target)
    if target:
        me["last_swipe"] = {"id": target, "action": action}   # rewind uchun
    save_db()
    res = {"match": False}
    if action in ("like", "message", "gift", "super") and target:
        res = await record_like(uid, target, text=text,
                                gift=(action == "gift"), sup=(action == "super"))
    return _json({"ok": True, "match": res.get("match", False),
                  "left": int(me.get("swipes_left", FREE_SWIPE_LIMIT)), "cap": FREE_SWIPE_LIMIT})


async def h_gift_invoice(request):
    """Virtual sovg'a uchun Stars invoice."""
    u = _auth(request)
    if not u:
        return _json({"error": "auth"}, 401)
    uid = str(u["id"])
    b = await request.json()
    gift = str(b.get("gift", ""))
    target = str(b.get("target", ""))
    g = GIFTS.get(gift)
    if not g or not target:
        return _json({"error": "bad"}, 400)
    if target == uid:
        return _json({"error": "self"}, 400)
    try:
        link = await bot.create_invoice_link(
            title=f"Sovg'a: {g['name']} {g['emoji']}",
            description="Luvora — virtual sovg'a",
            payload=f"gift:{gift}:{target}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=f"{g['name']} {g['emoji']}", amount=g["stars"])],
        )
        return _json({"link": link})
    except Exception as e:
        return _json({"error": "invoice_failed", "detail": str(e)}, 500)


async def h_request_premium(request):
    """Foydalanuvchi 'karta orqali' Premium so'raganda adminга xabar yuboradi."""
    u = _auth(request)
    if not u:
        return _json({"error": "auth"}, 401)
    uid = str(u["id"])
    me = get_user(uid)
    b = await request.json()
    plan = str(b.get("plan", ""))
    prod = STAR_PRODUCTS.get(plan) or STAR_PRODUCTS.get("prem" + plan)
    label = prod["title"] if prod else plan
    days = prod.get("days", 30) if prod else 30
    uname = ("@" + me["username"]) if me and me.get("username") else "—"
    txt = (
        "💳 Karta orqali Premium so'rovi\n"
        f"👤 {(me.get('name','') if me else '')} {uname}\n"
        f"🆔 {uid}\n"
        f"🎯 {label}\n\n"
        "To'lovni (chekni) tekshirib, bering:\n"
        f"/givepro {uid} {days}"
    )
    try:
        await bot.send_message(mod_target(), txt)
    except Exception:
        pass
    return _json({"ok": True})


async def h_invoice(request):
    """Telegram Stars invoice havolasini yaratadi."""
    u = _auth(request)
    if not u:
        return _json({"error": "auth"}, 401)
    uid = str(u["id"])
    body = await request.json()
    product = str(body.get("product", ""))
    prod = STAR_PRODUCTS.get(product)
    if not prod:
        return _json({"error": "bad_product"}, 400)
    try:
        link = await bot.create_invoice_link(
            title=prod["title"],
            description="Luvora — tanishuv ilovasi",
            payload=f"{uid}:{product}",
            provider_token="",          # Stars uchun bo'sh
            currency="XTR",
            prices=[LabeledPrice(label=prod["title"], amount=prod["stars"])],
        )
        return _json({"link": link})
    except Exception as e:
        logging.warning("Invoice yaratib bo'lmadi: %s", e)
        return _json({"error": "invoice_failed", "detail": str(e)}, 500)


async def h_rewind(request):
    u = _auth(request)
    if not u:
        return _json({"error": "auth"}, 401)
    uid = str(u["id"])
    me = get_user(uid)
    ls = me.get("last_swipe") if me else None
    if not ls:
        return _json({"ok": False, "error": "empty"})
    tid = str(ls.get("id"))
    # ko'rilganlardan olib tashlaymiz (yana chiqadi)
    me["seen"] = [s for s in me.get("seen", []) if s != tid]
    # limit zaxirasiga bittani qaytaramiz
    if ls.get("action") in ("like", "super", "pass"):
        me["swipes_left"] = min(FREE_SWIPE_LIMIT, int(me.get("swipes_left", 0) or 0) + 1)
    # yuborilgan laykni ham qaytaramiz
    if ls.get("action") in ("like", "super", "gift", "message"):
        tgt = get_user(tid)
        if tgt:
            tgt["likes_incoming"] = [l for l in tgt.get("likes_incoming", []) if l.get("from") != uid]
    me["last_swipe"] = None
    save_db()
    return _json({"ok": True, "profile": profile_json(tid, me)})


async def h_filter(request):
    u = _auth(request)
    if not u:
        return _json({"error": "auth"}, 401)
    uid = str(u["id"])
    me = get_user(uid)
    if not me:
        return _json({"error": "no_user"}, 400)
    if request.method == "GET":
        f = me.get("filter") or {}
        return _json({"age_min": f.get("age_min", 18), "age_max": f.get("age_max", 60),
                      "city": f.get("city", ""), "max_km": f.get("max_km", 0)})
    b = await request.json()
    try:
        amin = max(14, min(99, int(b.get("age_min", 18))))
        amax = max(14, min(99, int(b.get("age_max", 60))))
        if amin > amax:
            amin, amax = amax, amin
    except Exception:
        amin, amax = 18, 60
    me["filter"] = {
        "age_min": amin, "age_max": amax,
        "city": (b.get("city") or "").strip()[:40],
        "max_km": max(0, int(b.get("max_km", 0) or 0)),
    }
    me["seen"] = []   # filtr o'zgardi — yangidan ko'rsatamiz
    save_db()
    return _json({"ok": True})


async def h_likes(request):
    u = _auth(request)
    if not u:
        return _json({"error": "auth"}, 401)
    uid = str(u["id"])
    p = get_user(uid)
    prem = is_premium(p)
    out = []
    for like in (p.get("likes_incoming", []) if p else []):
        liker = profile_json(like["from"], p)
        if liker:
            liker["msg"] = like.get("text") if prem else None
            liker["super"] = bool(like.get("super"))
            liker["gift"] = like.get("gift_emoji")
            liker["locked"] = not prem       # premium bo'lmasa qulflangan (xira)
            if not prem:
                liker["name"] = ""           # ism yashiriladi
            out.append(liker)
    return _json({"items": out, "premium": prem})


async def h_like_decide(request):
    u = _auth(request)
    if not u:
        return _json({"error": "auth"}, 401)
    uid = str(u["id"])
    body = await request.json()
    from_id = str(body.get("from", ""))
    accept = bool(body.get("accept"))
    me = get_user(uid)
    liker = get_user(from_id)
    if not me:
        return _json({"error": "no_user"}, 400)
    me["likes_incoming"] = [l for l in me.get("likes_incoming", []) if l["from"] != from_id]
    contact = None
    if accept and liker:
        add_match(uid, from_id)
        my_contact = f"@{me['username']}" if me.get("username") else me.get("name")
        their = f"@{liker['username']}" if liker.get("username") else liker.get("name")
        contact = their
        if not from_id.startswith("demo"):
            try:
                await bot.send_message(int(from_id),
                                       t("mutual_notify", norm_lang(liker.get("language")), contact=my_contact))
            except Exception:
                pass
    save_db()
    return _json({"ok": True, "contact": contact})


async def h_logo(request):
    base = os.path.dirname(os.path.abspath(__file__))
    for nm in ("logo.png", "welcome.png"):
        path = os.path.join(base, nm)
        if os.path.exists(path):
            return web.FileResponse(path, headers={"Cache-Control": "public, max-age=3600"})
    return web.Response(status=404)


async def h_media(request):
    name = request.match_info["name"]
    if "/" in name or "\\" in name or ".." in name:
        return web.Response(status=404)
    path = os.path.join(UPLOAD_DIR, name)
    if not os.path.exists(path):
        return web.Response(status=404)
    return web.FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})


SEED_DIR = os.path.join(WEBAPP_DIR, "seed_photos")
_SEED_GRADS = [("#e3b26b", "#7a5a2a"), ("#c98bd6", "#5a2a6e"), ("#8bb8d6", "#2a4a6e"),
               ("#d68b9c", "#6e2a3a"), ("#8bd6a4", "#2a6e45"), ("#d6c98b", "#6e5a2a")]
_SEED_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def seed_photo_path(num) -> str:
    """<num> raqamli seed rasmi (har qanday kengaytmada) bo'lsa — yo'lini qaytaradi, aks holda ''."""
    for ext in _SEED_EXTS:
        p = os.path.join(SEED_DIR, f"{num}{ext}")
        if os.path.exists(p):
            return p
    return ""


_seed_photo_cache = {"ts": 0.0, "nums": set()}


def seed_has_photo(num) -> bool:
    """<num> uchun rasm bormi (30s keshlanadi)."""
    import time as _t
    now = _t.time()
    if now - _seed_photo_cache["ts"] > 30:
        nums = set()
        try:
            for fn in os.listdir(SEED_DIR):
                base, ext = os.path.splitext(fn)
                if base.isdigit() and ext.lower() in _SEED_EXTS:
                    nums.add(int(base))
        except Exception:
            pass
        _seed_photo_cache["nums"] = nums
        _seed_photo_cache["ts"] = now
    return int(num) in _seed_photo_cache["nums"]


async def h_seedphoto(request):
    """Seed anketa rasmi: miniapp/seed_photos/<raqam> bo'lsa beradi, bo'lmasa chiroyli placeholder."""
    name = request.match_info["name"]
    if "/" in name or "\\" in name or ".." in name:
        return web.Response(status=404)
    try:
        num = int("".join(ch for ch in name if ch.isdigit()) or "0")
    except Exception:
        num = 0
    fp = seed_photo_path(num)
    if fp:
        return web.FileResponse(fp, headers={"Cache-Control": "public, max-age=86400"})
    c1, c2 = _SEED_GRADS[num % len(_SEED_GRADS)]
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/>'
        f'</linearGradient></defs><rect width="600" height="800" fill="url(#g)"/>'
        f'<text x="300" y="420" font-size="200" text-anchor="middle" fill="#ffffff" '
        f'opacity="0.85" font-family="Arial">👩</text></svg>'
    )
    return web.Response(body=svg.encode("utf-8"), content_type="image/svg+xml",
                        headers={"Cache-Control": "no-store"})


async def h_upload(request):
    u = _auth(request)
    if not u:
        return _json({"error": "auth"}, 401)
    uid = str(u["id"])
    try:
        post = await request.post()
    except Exception:
        return _json({"error": "bad"}, 400)
    field = post.get("file")
    if field is None or not hasattr(field, "file"):
        return _json({"error": "no_file"}, 400)
    data = field.file.read()
    if not data or len(data) > 10 * 1024 * 1024:
        return _json({"error": "size"}, 400)
    fn = (getattr(field, "filename", "") or "").lower()
    ext = ".png" if fn.endswith(".png") else (".webp" if fn.endswith(".webp") else ".jpg")
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    import uuid as _uuid
    name = f"{uid}_{_uuid.uuid4().hex[:10]}{ext}"
    with open(os.path.join(UPLOAD_DIR, name), "wb") as f:
        f.write(data)
    return _json({"url": f"/media/{name}"})


async def h_register(request):
    u = _auth(request)
    if not u:
        return _json({"error": "auth"}, 401)
    uid = str(u["id"])
    b = await request.json()
    name = (b.get("name") or "").strip()
    age = b.get("age")
    gender = b.get("gender")
    goal = (b.get("goal") or "").strip()
    city = (b.get("city") or "").strip()
    about = (b.get("about") or "").strip()
    photos = b.get("photos") or []
    if not (name and age and gender in ("yigit", "qiz") and photos):
        return _json({"error": "invalid"}, 400)
    try:
        age = int(age)
    except Exception:
        return _json({"error": "age"}, 400)
    if not (14 <= age <= 99):
        return _json({"error": "age"}, 400)

    prof = get_user(uid) or {}
    prof.update({
        "id": uid,
        "username": u.get("username"),
        "name": name[:40],
        "age": age,
        "gender": gender,
        "goal": goal,
        "city": city[:40],
        "about": about[:400],
        "media": [{"type": "photo", "url": ph} for ph in photos[:6] if isinstance(ph, str)],
        "interest": prof.get("interest") or ("Qizlar" if gender == "yigit" else "Yigitlar"),
        "registered": True,
        "approved": False,
    })
    prof.setdefault("language", "🇺🇿 O'zbek")
    prof.setdefault("seen", [])
    prof.setdefault("likes_incoming", [])
    prof.setdefault("matches", [])
    prof.setdefault("created", today())
    prof.setdefault("banned", False)
    prof.setdefault("hidden", False)
    prof.setdefault("ref_count", 0)
    db["users"][uid] = prof

    # Referal: /start ref orqali kelган bo'lsa, taklif qilганга hisoblaymiz (bir marta)
    pend = db.get("pending_ref", {}).get(uid)
    if pend and not prof.get("ref_credited") and pend != uid:
        referrer = get_user(pend)
        if referrer:
            referrer["ref_count"] = referrer.get("ref_count", 0) + 1
            prof["ref_credited"] = True
            prof["ref_by"] = pend
            db["pending_ref"].pop(uid, None)
            rlng = norm_lang(referrer.get("language"))
            try:
                await bot.send_message(int(pend), t("ref_credited", rlng))
            except Exception:
                pass
            # Adminga xabar: kim kimni taklif qildi, jami nechta
            try:
                ref_u = ("@" + referrer["username"]) if referrer.get("username") else referrer.get("name", "—")
                new_u = ("@" + prof["username"]) if prof.get("username") else prof.get("name", "—")
                await bot.send_message(
                    mod_target(),
                    f"👥 Referal!\n"
                    f"Yangi: {new_u} (ID {uid})\n"
                    f"Taklif qilgan: {ref_u} (ID {pend})\n"
                    f"➡️ Bu odam jami {referrer['ref_count']} ta taklif qildi."
                )
            except Exception:
                pass
            # har 5 ta taklif = 1 oy Premium sovg'a
            if referrer["ref_count"] % 5 == 0:
                import time as _t
                now = int(_t.time() * 1000)
                base = max(now, int(referrer.get("premium_until", 0) or 0))
                referrer["premium_until"] = base + 30 * 86400 * 1000
                referrer["boost_until"] = referrer["premium_until"]
                gift_msg = {
                    "uz": "🎉 5 ta do'st taklif qildingiz — 1 oylik Premium sovg'a sizga berildi! 👑",
                    "ru": "🎉 Вы пригласили 5 друзей — Premium на 1 месяц в подарок! 👑",
                }[rlng]
                try:
                    await bot.send_message(int(pend), gift_msg, reply_markup=app_kb())
                except Exception:
                    pass
    save_db()
    # Tasdiqlash botda: telefon -> krujok. (Moderatsiya krujokdan keyin.)
    plng = norm_lang(prof.get("language"))
    try:
        await bot.send_message(
            int(uid),
            "✅ Anketa yaratildi!\n\n"
            "🪪 Bottan to'liq foydalanish uchun identifikatsiyadan o'ting.\n\n"
            "1️⃣ Telefon raqamingizni yuboring 👇\n"
            "2️⃣ So'ng video-krujok yozib yuborasiz\n\n"
            "(Raqamingizni boshqa foydalanuvchilar ko'rmaydi)",
            reply_markup=phone_kb(plng),
        )
    except Exception:
        pass
    return _json({"ok": True, "verify": True})


def pair_key(a, b) -> str:
    return "|".join(sorted([str(a), str(b)]))


def now_ms() -> int:
    import time
    return int(time.time() * 1000)


async def h_update_profile(request):
    u = _auth(request)
    if not u:
        return _json({"error": "auth"}, 401)
    uid = str(u["id"])
    p = get_user(uid)
    if not p or not p.get("registered"):
        return _json({"error": "noprofile"}, 400)
    b = await request.json()

    if b.get("name") and str(b["name"]).strip():
        p["name"] = str(b["name"]).strip()[:40]
    if "about" in b:
        p["about"] = (b.get("about") or "").strip()[:400]
    if b.get("city"):
        p["city"] = str(b["city"]).strip()[:40]
    for k in ("goal", "pets", "habits", "sport", "education", "family", "comm"):
        if k in b:
            p[k] = (b.get(k) or "")[:60]
    if "height" in b:
        try:
            p["height"] = int(b["height"]) if b.get("height") else None
        except Exception:
            pass
    try:
        p["pref_age_min"] = max(14, min(99, int(b.get("pref_age_min", p.get("pref_age_min", 18)))))
        p["pref_age_max"] = max(14, min(99, int(b.get("pref_age_max", p.get("pref_age_max", 65)))))
        if p["pref_age_min"] > p["pref_age_max"]:
            p["pref_age_min"], p["pref_age_max"] = p["pref_age_max"], p["pref_age_min"]
    except Exception:
        pass
    if isinstance(b.get("interests"), list):
        p["interests"] = [str(x)[:30] for x in b["interests"][:12]]
    if b.get("age"):
        try:
            a = int(b["age"])
            if 14 <= a <= 99:
                p["age"] = a
        except Exception:
            pass
    # rasmlar (tartiblangan/yangilangan): [{type,url|file_id}, ...]
    if isinstance(b.get("media"), list) and b["media"]:
        clean = []
        for m in b["media"][:6]:
            if not isinstance(m, dict):
                continue
            if m.get("file_id"):
                clean.append({"type": "photo", "file_id": m["file_id"]})
            elif m.get("url"):
                clean.append({"type": "photo", "url": m["url"]})
        if clean:
            p["media"] = clean
    save_db()
    return _json({"ok": True})


async def h_chats(request):
    u = _auth(request)
    if not u:
        return _json({"error": "auth"}, 401)
    uid = str(u["id"])
    p = get_user(uid)
    out = []
    msgs = db.get("messages", {})
    for mid in (p.get("matches", []) if p else []):
        prof = profile_json(mid, p)
        if prof:
            m = get_user(mid)
            prof["username"] = m.get("username") if m else None
            arr = msgs.get(pair_key(uid, mid), [])
            last = arr[-1] if arr else None
            prof["last"] = last["text"] if last else None
            prof["lastTs"] = last["ts"] if last else 0
            out.append(prof)
    out.sort(key=lambda x: x.get("lastTs", 0), reverse=True)
    return _json({"items": out})


async def h_messages(request):
    u = _auth(request)
    if not u:
        return _json({"error": "auth"}, 401)
    uid = str(u["id"])
    other = str(request.query.get("with", ""))
    after = int(request.query.get("after", "0") or 0)
    arr = db.get("messages", {}).get(pair_key(uid, other), [])
    items = [m for m in arr if m["ts"] > after]
    return _json({"items": items, "me": uid})


async def h_send(request):
    u = _auth(request)
    if not u:
        return _json({"error": "auth"}, 401)
    uid = str(u["id"])
    body = await request.json()
    to = str(body.get("to", ""))
    text = (body.get("text") or "").strip()[:1000]
    me = get_user(uid)
    if not me or not text:
        return _json({"error": "bad"}, 400)
    if to not in me.get("matches", []):
        return _json({"error": "not_matched"}, 403)
    msg = {"from": uid, "text": text, "ts": now_ms()}
    db.setdefault("messages", {}).setdefault(pair_key(uid, to), []).append(msg)
    save_db()
    if not to.startswith("demo") and not is_online(get_user(to)):
        try:
            nm = me.get("name", "")
            await bot.send_message(int(to), f"💬 {nm}: {text[:120]}\nJavob berish uchun ilovani och 👇", reply_markup=app_kb())
        except Exception:
            pass
    return _json({"ok": True, "msg": msg})


async def h_visibility(request):
    u = _auth(request)
    if not u:
        return _json({"error": "auth"}, 401)
    p = get_user(str(u["id"]))
    if not p:
        return _json({"error": "no_user"}, 400)
    body = await request.json()
    p["hidden"] = not bool(body.get("visible", True))
    save_db()
    return _json({"ok": True, "visible": not p["hidden"]})


async def h_check_sub(request):
    u = _auth(request)
    if not u:
        return _json({"error": "auth"}, 401)
    uid = str(u["id"])
    p = get_user(uid)
    if not p:
        return _json({"error": "no_user"}, 400)
    ok = await check_channel_sub(uid)
    if ok:
        p["channel_sub"] = True
        save_db()
    return _json({"ok": True, "subscribed": ok, "channel": CHANNEL_URL})


async def h_set_lang(request):
    u = _auth(request)
    if not u:
        return _json({"error": "auth"}, 401)
    p = get_user(str(u["id"]))
    if not p:
        return _json({"error": "no_user"}, 400)
    body = await request.json()
    lng = "ru" if str(body.get("lng", "")).startswith("ru") else "uz"
    p["language"] = "🇷🇺 Русский" if lng == "ru" else "🇺🇿 O'zbek"
    save_db()
    return _json({"ok": True, "lng": lng})


async def h_report(request):
    u = _auth(request)
    if not u:
        return _json({"error": "auth"}, 401)
    uid = str(u["id"])
    body = await request.json()
    target = str(body.get("target", ""))
    p = get_user(target)
    if p:
        p["reports"] = p.get("reports", 0) + 1
        if p["reports"] >= 5:      # 5+ shikoyat — avtomatik yashirish
            p["hidden"] = True
        me = get_user(uid)
        if me is not None and target not in me.setdefault("seen", []):
            me["seen"].append(target)
        save_db()
    return _json({"ok": True})


async def h_delete_account(request):
    u = _auth(request)
    if not u:
        return _json({"error": "auth"}, 401)
    uid = str(u["id"])
    purge_user(uid)
    return _json({"ok": True, "deleted": True})


def build_web_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", h_index)
    app.router.add_get("/logo", h_logo)
    app.router.add_get("/photo/{uid}/{idx}", h_photo)
    app.router.add_get("/api/me", h_me)
    app.router.add_get("/api/feed", h_feed)
    app.router.add_post("/api/act", h_act)
    app.router.add_get("/api/likes", h_likes)
    app.router.add_post("/api/like_decide", h_like_decide)
    app.router.add_get("/api/chats", h_chats)
    app.router.add_post("/api/visibility", h_visibility)
    app.router.add_post("/api/set_lang", h_set_lang)
    app.router.add_post("/api/check_sub", h_check_sub)
    app.router.add_post("/api/delete_account", h_delete_account)
    app.router.add_post("/api/report", h_report)
    app.router.add_get("/media/{name}", h_media)
    app.router.add_get("/seedphoto/{name}", h_seedphoto)
    app.router.add_post("/api/upload", h_upload)
    app.router.add_post("/api/register", h_register)
    app.router.add_get("/api/messages", h_messages)
    app.router.add_post("/api/message", h_send)
    app.router.add_post("/api/update_profile", h_update_profile)
    app.router.add_post("/api/rewind", h_rewind)
    app.router.add_get("/api/filter", h_filter)
    app.router.add_post("/api/filter", h_filter)
    app.router.add_post("/api/invoice", h_invoice)
    app.router.add_post("/api/gift_invoice", h_gift_invoice)
    app.router.add_post("/api/request_premium", h_request_premium)
    return app


@dp.message(Command("app"))
async def cmd_app(message: Message):
    if not WEBAPP_URL:
        await message.answer("Mini App hali sozlanmagan. (WEBAPP_URL bo'sh)")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💞 Luvora'ni ochish", web_app=WebAppInfo(url=WEBAPP_URL))
    ]])
    await message.answer("Zamonaviy tanishuv ilovasini och 👇", reply_markup=kb)


async def setup_menu_button():
    """Chatdagi menyu tugmasini Mini App'ga ulash (agar URL bo'lsa)."""
    try:
        if WEBAPP_URL:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="💞 Luvora", web_app=WebAppInfo(url=WEBAPP_URL))
            )
        else:
            await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except Exception as e:
        logging.warning("Menyu tugmasini sozlab bo'lmadi: %s", e)


def migrate_db():
    """Eski anketalardagi jins/qiziqish qiymatlarini yangi ko'rinishga keltiradi."""
    changed = False
    for p in db["users"].values():
        g = norm_gender(p.get("gender"))
        if g != p.get("gender"):
            p["gender"] = g
            changed = True
        i = p.get("interest")
        if i is not None:
            ni = norm_interest(i)
            if ni != i:
                p["interest"] = ni
                changed = True
    if changed:
        save_db()


async def main():
    global BOT_USERNAME, WEBAPP_URL
    seed_demo()
    migrate_db()
    if not db.get("seeded_v2"):
        # eski seedlarni o'chirib, yosh 18-24 bilan qayta yaratamiz
        for k in [k for k in list(db["users"]) if k.startswith("demo_s")]:
            db["users"].pop(k, None)
        seed_bot_profiles(300)
        db["seeded_v2"] = True
        save_db()
        logging.info("✅ 300 ta boshlang'ich (Toshkent, 18-24) anketa qo'shildi.")

    # WEBAPP_URL ni webapp_url.txt fayldan o'qish (agar bo'lsa) — botni tahrirlamaslik uchun
    _url = _load_webapp_url()
    if _url:
        WEBAPP_URL = _url
        logging.info("WEBAPP_URL webapp_url.txt dan olindi: %s", WEBAPP_URL)

    # 1) Mini App web-serverini AVVAL ishga tushiramiz — Telegram uzilса ham ishlab tursin
    web_app = build_web_app()
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WEB_PORT)
    await site.start()
    logging.info("Mini App web-server: http://127.0.0.1:%s (WEBAPP_URL=%s)", WEB_PORT, WEBAPP_URL or "bo'sh")

    # 1.5) cloudflared.exe bor bo'lsa — tunnelni AVTOMATIK ochamiz (URL har safar yangilanadi)
    logging.info("cloudflared tunnel ochilmoqda... (biroz kuting)")
    _tun = start_cloudflared_tunnel()
    if _tun:
        WEBAPP_URL = _tun
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp_url.txt"), "w", encoding="utf-8") as f:
                f.write(_tun)
        except Exception:
            pass
        logging.info("✅ Tunnel tayyor: %s", WEBAPP_URL)
    elif WEBAPP_URL:
        logging.info("Tunnel ochilmadi — webapp_url.txt dagi manzil ishlatiladi: %s", WEBAPP_URL)
    else:
        logging.warning("⚠️ Tunnel ham, webapp_url.txt ham yo'q — Mini App tugmasi ishlamaydi.")

    # 2) Telegram'ga ulanish — tarmoq uzilса qayta urinadi (web-server ishlab turaveradi)
    try:
        while True:
            try:
                me = await bot.get_me()
                BOT_USERNAME = me.username
                logging.info("Bot ishga tushdi: @%s", BOT_USERNAME)
                await setup_menu_button()
                try:
                    await bot.set_my_short_description("O'zbekistonda tanishuv ilovasi 💞")
                    await bot.set_my_description(
                        "Luvora — tez va zamonaviy tanishuv 💛\n"
                        "🔥 Anketalar  💛 Matchlar  💬 Telegram ichida suhbat\n\n"
                        "Boshlash uchun /start bosing."
                    )
                    await bot.set_my_commands([
                        BotCommand(command="start", description="💞 Ilovani ochish"),
                        BotCommand(command="app", description="Luvora'ni ochish"),
                        BotCommand(command="invite", description="🎁 Do'st taklif qilish"),
                    ])
                except Exception as e:
                    logging.warning("Bot profilini sozlab bo'lmadi: %s", e)
                # Kanalga bir martalik reklama-post (bot kanalda admin bo'lishi kerak)
                try:
                    if not db.get("promo_posted"):
                        ok, info = await post_channel_promo()
                        if ok:
                            db["promo_posted"] = True
                            save_db()
                            logging.info("✅ Kanalga reklama-post joylandi va pin qilindi.")
                        else:
                            logging.warning("❌ Kanalga post joylab bo'lmadi: %s", info)
                except Exception as e:
                    logging.warning("Kanal post xato: %s", e)
                # Kanalga bir martalik maslahat-postlar
                try:
                    if not db.get("advice_posted"):
                        ok2, info2 = await post_channel_advice()
                        if ok2:
                            db["advice_posted"] = True
                            save_db()
                            logging.info("✅ Kanalga 3 ta maslahat-post joylandi.")
                        else:
                            logging.warning("❌ Maslahat-postlarni joylab bo'lmadi: %s", info2)
                except Exception as e:
                    logging.warning("Maslahat post xato: %s", e)
                # Avtomatik kunlik kanal postlari (bir marta ishga tushadi)
                if AUTO_POST_ENABLED and not getattr(main, "_autopost_started", False):
                    asyncio.create_task(channel_autopost_loop())
                    main._autopost_started = True
                    logging.info("🕒 Avtomatik kanal postlari yoqildi (har kuni soat %02d:00).", AUTO_POST_HOUR)
                await dp.start_polling(bot)
                break
            except Exception as e:
                logging.warning("Telegram'ga ulanib bo'lmadi: %s | 5s dan keyin qayta urinaman (Mini App ishlayapti)", e)
                await asyncio.sleep(5)
    finally:
        await runner.cleanup()
        if _TUNNEL_PROC is not None:
            try:
                _TUNNEL_PROC.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())
