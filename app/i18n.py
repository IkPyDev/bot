"""
Lokalizatsiya (i18n) moduli — foydalanuvchiga ko'rinadigan matnlar ko'p tilda.

NIMA QILADI:
- Foydalanuvchi /start bosganda uning Telegram tilini (language_code) aniqlaydi
  va matnni o'sha tilda qaytaradi.
- Til topilmasa yoki qo'llab-quvvatlanmasa — INGLIZCHA (en) ga tushadi (fallback).

QO'LLAB-QUVVATLANADIGAN TILLAR (MDH):
- en — English (default / fallback)
- ru — Русский
- uz — O'zbekcha
- tg — Тоҷикӣ (tojikcha)
- kk — Қазақша (qozoqcha)
- ky — Кыргызча (qirg'izcha)

QANDAY ISHLATILADI:
    from app.i18n import t, pick_lang

    lang = pick_lang(user.language_code)   # "en" / "ru" / "uz" / ...
    caption = t(lang, "start_caption")     # o'sha tildagi matn
    button  = t(lang, "btn_connect")

YANGI TIL QO'SHISH:
- TRANSLATIONS ga yangi til kodi (masalan "az") uchun barcha kalitlarni qo'shing.
- Kerak bo'lsa LANG_ALIASES ga variantlarini (masalan "az-AZ" -> "az") qo'shing.

YANGI MATN (kalit) QO'SHISH:
- Har bir til uchun TRANSLATIONS ga o'sha kalitni qo'shing.
- Agar biror tilda kalit bo'lmasa — avtomatik inglizchasi ishlatiladi.
"""

from typing import Optional

# Bot username — matnlarda {bot} placeholder o'rniga qo'yiladi.
# O'zgarsa faqat shu yerni yangilash yetarli.
BOT_USERNAME = "@sirsaqlauzbot"

# Default (fallback) til — qo'llab-quvvatlanmagan til uchun ishlatiladi.
DEFAULT_LANG = "en"

# Qo'llab-quvvatlanadigan til kodlari.
SUPPORTED_LANGS = ("en", "ru", "uz", "tg", "kk", "ky")

# Telegram ba'zan "en-US", "ru-RU" yoki eski/muqobil kodlar yuboradi.
# Ularni bizning asosiy kodlarimizga bog'laymiz.
LANG_ALIASES = {
    "uz-latn": "uz",
    "uz-cyrl": "uz",
    "tg-tj": "tg",
    "tgk": "tg",
    "kk-kz": "kk",
    "kaz": "kk",
    "ky-kg": "ky",
    "kir": "ky",
}


def pick_lang(language_code: Optional[str]) -> str:
    """
    Telegram'ning language_code'idan bizning til kodimizni tanlaydi.

    Misollar:
        "ru"      -> "ru"
        "en-US"   -> "en"
        "uz-Latn" -> "uz"
        "de"      -> "en"  (qo'llab-quvvatlanmaydi — fallback)
        None      -> "en"
    """
    if not language_code:
        return DEFAULT_LANG

    code = language_code.strip().lower()

    # To'liq kod alias'da bo'lsa (masalan "uz-latn")
    if code in LANG_ALIASES:
        return LANG_ALIASES[code]

    # Faqat til qismini olamiz: "en-us" -> "en"
    base = code.split("-", 1)[0]
    if base in LANG_ALIASES:
        return LANG_ALIASES[base]
    if base in SUPPORTED_LANGS:
        return base

    return DEFAULT_LANG


def t(lang: str, key: str) -> str:
    """
    Berilgan til va kalit bo'yicha matnni qaytaradi.

    - Til qo'llab-quvvatlanmasa yoki kalit o'sha tilda bo'lmasa — inglizchasi.
    - {bot} placeholder avtomatik BOT_USERNAME ga almashtiriladi.
    """
    table = TRANSLATIONS.get(lang) or TRANSLATIONS[DEFAULT_LANG]
    text = table.get(key)
    if text is None:
        text = TRANSLATIONS[DEFAULT_LANG].get(key, "")
    return text.replace("{bot}", BOT_USERNAME)


# ============================================================
# TARJIMALAR
# Har bir til — kalit: matn. {bot} — bot username placeholder'i.
# ============================================================

TRANSLATIONS: dict[str, dict[str, str]] = {
    # --------------------------------------------------------
    # ENGLISH (default / fallback)
    # --------------------------------------------------------
    "en": {
        "btn_connect": "🔌 Connect",
        "btn_android": "🤖 Connect on Android",
        "btn_ios": "🍏 Connect on iOS",
        "start_caption": (
            "<b>🕵️‍♂️ Welcome!</b>\n"
            "I keep an eye on your chats for you.\n\n"
            "<b>📌 What I can do:</b>\n\n"
            "🔔 If the person you're talking to <b>edits</b> a message — I'll show you the old text\n"
            "🗑 If they <b>delete</b> a message — I'll keep a copy of what they wrote\n"
            "⏳ I'll save <b>view-once</b> photos, videos, voice messages and round videos\n\n"
            "➖➖➖➖➖➖➖➖➖\n\n"
            "<b>⚡️ Set up in 3 simple steps:</b>\n\n"
            "1️⃣ Tap the <b>«🔌 Connect»</b> button below 👇\n\n"
            "2️⃣ In the window that opens, choose <b>«Chatbots»</b> 🤖\n\n"
            "3️⃣ Type the bot name into the empty field 👇\n"
            "<code>{bot}</code>\n"
            "The bot will appear below — <b>tap on it</b> ✅\n\n"
            "➖➖➖➖➖➖➖➖➖\n\n"
        ),
        "android_caption": (
            "<b>🤖 Connecting on an Android phone</b>\n\n"
            "1️⃣ Open Telegram <b>Settings</b> ⚙️\n\n"
            "2️⃣ Go to <b>«My Account»</b> 👤\n\n"
            "3️⃣ Choose <b>«Chatbots»</b> 🤖\n\n"
            "4️⃣ Type the bot name into the empty field 👇\n"
            "<code>{bot}</code>\n\n"
            "5️⃣ Tap the bot that appears below ✅\n\n"
            "<blockquote>💡 Everything is shown in the video above — just repeat it.</blockquote>"
        ),
        "ios_caption": (
            "<b>🍏 Connecting on an iPhone (iOS)</b>\n\n"
            "1️⃣ Open Telegram <b>Settings</b> ⚙️\n\n"
            "2️⃣ Tap <b>«Edit»</b> ✏️\n\n"
            "3️⃣ Choose <b>«Chatbots»</b> 🤖\n\n"
            "4️⃣ Type the bot name into the empty field 👇\n"
            "<code>{bot}</code>\n\n"
            "5️⃣ Tap the bot that appears below ✅\n\n"
            "<blockquote>💡 Everything is shown in the video above — just repeat it.</blockquote>"
        ),
        "connect_caption": (
            "✅ <b>The bot has been connected successfully</b>\n\n"
            "<b>How to use it?</b>\n"
            "➖ If the person you're chatting with deletes a message, the bot will "
            "immediately send you a copy of it (works only with messages sent AFTER "
            "the bot was connected)\n"
            "➖ To save timed (view-once) photos/videos, you need to reply to them with "
            "any message in the chat with that person (the video ☝️ shows an example) "
            "(BEFORE OPENING THEM — THIS IS IMPORTANT!)\n\n"
            "❗ The bot only works with NEW messages received after it was connected"
        ),
        # Bildirishnoma yorliqlari (owner'ga — tahrir/o'chirish)
        "n_edit_title": "✏️ Message edited",
        "n_del_title": "🗑 Message deleted",
        "n_label_chat": "💬 Chat:",
        "n_edit_old": "📝 Old:",
        "n_edit_new": "✅ New:",
        "n_del_deleted_at": "🕐 Deleted at:",
        "n_del_sent_at": "🕐 Sent at:",
        "n_media_failed": "media could not be sent",
        "n_label_text": "Text:",
    },

    # --------------------------------------------------------
    # РУССКИЙ
    # --------------------------------------------------------
    "ru": {
        "btn_connect": "🔌 Подключить",
        "btn_android": "🤖 Подключить на Android",
        "btn_ios": "🍏 Подключить на iOS",
        "start_caption": (
            "<b>🕵️‍♂️ Добро пожаловать!</b>\n"
            "Я слежу за вашими перепиской вместо вас.\n\n"
            "<b>📌 Что я умею:</b>\n\n"
            "🔔 Если собеседник <b>отредактирует</b> сообщение — я покажу старый текст\n"
            "🗑 Если <b>удалит</b> сообщение — я сохраню копию того, что было написано\n"
            "⏳ Сохраняю фото, видео, голосовые и кружочки с <b>одноразовым просмотром</b>\n\n"
            "➖➖➖➖➖➖➖➖➖\n\n"
            "<b>⚡️ Настройка — 3 простых шага:</b>\n\n"
            "1️⃣ Нажмите кнопку <b>«🔌 Подключить»</b> ниже 👇\n\n"
            "2️⃣ В открывшемся окне выберите <b>«Чат-боты»</b> 🤖\n\n"
            "3️⃣ Введите имя бота в пустое поле 👇\n"
            "<code>{bot}</code>\n"
            "Ниже появится бот — <b>нажмите на него</b> ✅\n\n"
            "➖➖➖➖➖➖➖➖➖\n\n"
        ),
        "android_caption": (
            "<b>🤖 Подключение на телефоне Android</b>\n\n"
            "1️⃣ Откройте <b>Настройки</b> Telegram ⚙️\n\n"
            "2️⃣ Перейдите в раздел <b>«Мой аккаунт»</b> 👤\n\n"
            "3️⃣ Выберите <b>«Чат-боты»</b> 🤖\n\n"
            "4️⃣ Введите имя бота в пустое поле 👇\n"
            "<code>{bot}</code>\n\n"
            "5️⃣ Нажмите на бота, который появится ниже ✅\n\n"
            "<blockquote>💡 Всё показано в видео выше — просто повторите.</blockquote>"
        ),
        "ios_caption": (
            "<b>🍏 Подключение на iPhone (iOS)</b>\n\n"
            "1️⃣ Откройте <b>Настройки</b> Telegram ⚙️\n\n"
            "2️⃣ Нажмите <b>«Редактировать»</b> ✏️\n\n"
            "3️⃣ Выберите <b>«Чат-боты»</b> 🤖\n\n"
            "4️⃣ Введите имя бота в пустое поле 👇\n"
            "<code>{bot}</code>\n\n"
            "5️⃣ Нажмите на бота, который появится ниже ✅\n\n"
            "<blockquote>💡 Всё показано в видео выше — просто повторите.</blockquote>"
        ),
        "connect_caption": (
            "✅ <b>Бот успешно подключён</b>\n\n"
            "<b>Как пользоваться?</b>\n"
            "➖ Если собеседник удалит сообщение, бот сразу пришлёт вам его копию "
            "(работает только с сообщениями, отправленными ПОСЛЕ подключения бота)\n"
            "➖ Чтобы сохранить фото/видео с таймером (одноразовые), нужно ответить на них "
            "любым сообщением в диалоге с этим человеком (в видео ☝️ показан пример) "
            "(ДО ТОГО КАК ОТКРЫТЬ, ЭТО ВАЖНО!)\n\n"
            "❗ Бот работает только с НОВЫМИ сообщениями, полученными после подключения"
        ),
        "n_edit_title": "✏️ Сообщение отредактировано",
        "n_del_title": "🗑 Сообщение удалено",
        "n_label_chat": "💬 Чат:",
        "n_edit_old": "📝 Старое:",
        "n_edit_new": "✅ Новое:",
        "n_del_deleted_at": "🕐 Удалено:",
        "n_del_sent_at": "🕐 Отправлено:",
        "n_media_failed": "медиа не отправлено",
        "n_label_text": "Текст:",
    },

    # --------------------------------------------------------
    # O'ZBEKCHA
    # --------------------------------------------------------
    "uz": {
        "btn_connect": "🔌 Ulash",
        "btn_android": "🤖 Android ulash",
        "btn_ios": "🍏 iOS ulash",
        "start_caption": (
            "<b>🕵️‍♂️ Xush kelibsiz!</b>\n"
            "Men sizning yozishmalaringizni kuzatib turaman.\n\n"
            "<b>📌 Nima qila olaman:</b>\n\n"
            "🔔 Suhbatdoshingiz xabarini <b>tahrirlasa</b> — eski matnini ko'rsataman\n"
            "🗑 Xabarni <b>o'chirsa</b> — nima yozganini saqlab qolaman\n"
            "⏳ <b>Bir marta ko'riladigan</b> surat, video, ovozli xabar va yumoloq videolarni yuklab olaman\n\n"
            "➖➖➖➖➖➖➖➖➖\n\n"
            "<b>⚡️ Ishga tushirish — 3 ta oddiy qadam:</b>\n\n"
            "1️⃣ Pastdagi <b>«🔌 Ulash»</b> tugmasini bosing 👇\n\n"
            "2️⃣ Ochilgan oynadan <b>«Chatlarni avtomatlashtirish»</b> bo'limini tanlang 🤖\n\n"
            "3️⃣ Bo'sh maydonga bot nomini yozing 👇\n"
            "<code>{bot}</code>\n"
            "Pastda bot chiqadi — <b>bot ustiga bosing</b> ✅\n\n"
            "➖➖➖➖➖➖➖➖➖\n\n"
        ),
        "android_caption": (
            "<b>🤖 Android telefonda ulash</b>\n\n"
            "1️⃣ Telegram <b>Sozlamalar</b>ini oching ⚙️\n\n"
            "2️⃣ <b>«Hisob»</b> bo'limiga o'ting 👤\n\n"
            "3️⃣ <b>«Chatlarni avtomatlashtirish»</b>ni tanlang 🤖\n\n"
            "4️⃣ Bo'sh maydonga bot nomini yozing 👇\n"
            "<code>{bot}</code>\n\n"
            "5️⃣ Pastda chiqqan bot ustiga bosing ✅\n\n"
            "<blockquote>💡 Yuqoridagi videoda hammasi ko'rsatilgan — shunday takrorlang.</blockquote>"
        ),
        "ios_caption": (
            "<b>🍏 iPhone (iOS) da ulash</b>\n\n"
            "1️⃣ Telegram <b>Sozlamalar</b>ini oching ⚙️\n\n"
            "2️⃣ <b>«Tahrirlash»</b> tugmasini bosing ✏️\n\n"
            "3️⃣ <b>«Chatlarni avtomatlashtirish»</b>ni tanlang 🤖\n\n"
            "4️⃣ Bo'sh maydonga bot nomini yozing 👇\n"
            "<code>{bot}</code>\n\n"
            "5️⃣ Pastda chiqqan bot ustiga bosing ✅\n\n"
            "<blockquote>💡 Yuqoridagi videoda hammasi ko'rsatilgan — shunday takrorlang.</blockquote>"
        ),
        "connect_caption": (
            "✅ <b>Bot muvaffaqiyatli ulandi</b>\n\n"
            "<b>Qanday foydalanish kerak?</b>\n"
            "➖ Agar suhbatdoshingiz xabarni o'chirsa, bot darhol sizga o'sha xabar "
            "nusxasini yuboradi (faqat bot ulangandan KEYIN yuborilgan xabarlar bilan ishlaydi)\n"
            "➖ Taymerli surat/videolarni yuklab olish uchun, suhbatdoshingiz bilan dialogda "
            "ularga istalgan xabar bilan javob berishingiz kerak (videoda ☝️ misol ko'rsatilgan) "
            "(OCHISHDAN OLDIN, BU MUHIM!)\n\n"
            "❗ Bot faqat bot ulangandan keyin olingan YANGI xabarlar bilan ishlaydi"
        ),
        "n_edit_title": "✏️ Xabar tahrirlandi",
        "n_del_title": "🗑 Xabar o'chirildi",
        "n_label_chat": "💬 Chat:",
        "n_edit_old": "📝 Eski:",
        "n_edit_new": "✅ Yangi:",
        "n_del_deleted_at": "🕐 O'chirilgan vaqt:",
        "n_del_sent_at": "🕐 Yuborilgan vaqt:",
        "n_media_failed": "media yuborilmadi",
        "n_label_text": "Matn:",
    },

    # --------------------------------------------------------
    # ТОҶИКӢ (tojikcha)
    # --------------------------------------------------------
    "tg": {
        "btn_connect": "🔌 Пайваст кардан",
        "btn_android": "🤖 Дар Android пайваст",
        "btn_ios": "🍏 Дар iOS пайваст",
        "start_caption": (
            "<b>🕵️‍♂️ Хуш омадед!</b>\n"
            "Ман ба ҷои шумо мукотибаи шуморо назорат мекунам.\n\n"
            "<b>📌 Ман чӣ карда метавонам:</b>\n\n"
            "🔔 Агар ҳамсӯҳбататон паёмро <b>таҳрир</b> кунад — матни кӯҳнаро нишон медиҳам\n"
            "🗑 Агар паёмро <b>нест</b> кунад — нусхаи навишташударо нигоҳ медорам\n"
            "⏳ Аксу видео, паёми овозӣ ва видеоҳои доирашаклро, ки <b>якдафъа дида мешаванд</b>, нигоҳ медорам\n\n"
            "➖➖➖➖➖➖➖➖➖\n\n"
            "<b>⚡️ Танзим — 3 қадами оддӣ:</b>\n\n"
            "1️⃣ Тугмаи <b>«🔌 Пайваст кардан»</b>-ро дар поён пахш кунед 👇\n\n"
            "2️⃣ Дар тирезаи кушодашуда <b>«Чатботҳо»</b>-ро интихоб кунед 🤖\n\n"
            "3️⃣ Номи ботро ба майдони холӣ нависед 👇\n"
            "<code>{bot}</code>\n"
            "Дар поён бот пайдо мешавад — <b>ба он пахш кунед</b> ✅\n\n"
            "➖➖➖➖➖➖➖➖➖\n\n"
        ),
        "android_caption": (
            "<b>🤖 Пайваст дар телефони Android</b>\n\n"
            "1️⃣ <b>Танзимот</b>-и Telegram-ро кушоед ⚙️\n\n"
            "2️⃣ Ба бахши <b>«Ҳисоби ман»</b> гузаред 👤\n\n"
            "3️⃣ <b>«Чатботҳо»</b>-ро интихоб кунед 🤖\n\n"
            "4️⃣ Номи ботро ба майдони холӣ нависед 👇\n"
            "<code>{bot}</code>\n\n"
            "5️⃣ Ба боти дар поён пайдошуда пахш кунед ✅\n\n"
            "<blockquote>💡 Ҳама чиз дар видеои боло нишон дода шудааст — ҳамин тавр такрор кунед.</blockquote>"
        ),
        "ios_caption": (
            "<b>🍏 Пайваст дар iPhone (iOS)</b>\n\n"
            "1️⃣ <b>Танзимот</b>-и Telegram-ро кушоед ⚙️\n\n"
            "2️⃣ Тугмаи <b>«Таҳрир кардан»</b>-ро пахш кунед ✏️\n\n"
            "3️⃣ <b>«Чатботҳо»</b>-ро интихоб кунед 🤖\n\n"
            "4️⃣ Номи ботро ба майдони холӣ нависед 👇\n"
            "<code>{bot}</code>\n\n"
            "5️⃣ Ба боти дар поён пайдошуда пахш кунед ✅\n\n"
            "<blockquote>💡 Ҳама чиз дар видеои боло нишон дода шудааст — ҳамин тавр такрор кунед.</blockquote>"
        ),
        "connect_caption": (
            "✅ <b>Бот бомуваффақият пайваст шуд</b>\n\n"
            "<b>Чӣ тавр истифода бурдан мумкин?</b>\n"
            "➖ Агар ҳамсӯҳбататон паёмро нест кунад, бот фавран ба шумо нусхаи онро мефиристад "
            "(танҳо бо паёмҳое кор мекунад, ки ПАС АЗ пайвасти бот фиристода шудаанд)\n"
            "➖ Барои нигоҳ доштани аксу видеои таймердор (якдафъа), бояд ба онҳо бо ягон паём "
            "дар муколама бо ҳамон шахс ҷавоб диҳед (дар видео ☝️ мисол нишон дода шудааст) "
            "(ПЕШ АЗ КУШОДАН, ИН МУҲИМ АСТ!)\n\n"
            "❗ Бот танҳо бо паёмҳои НАВ, ки пас аз пайваст гирифта шудаанд, кор мекунад"
        ),
        "n_edit_title": "✏️ Паём таҳрир шуд",
        "n_del_title": "🗑 Паём нест карда шуд",
        "n_label_chat": "💬 Чат:",
        "n_edit_old": "📝 Кӯҳна:",
        "n_edit_new": "✅ Нав:",
        "n_del_deleted_at": "🕐 Нест карда шуд:",
        "n_del_sent_at": "🕐 Фиристода шуд:",
        "n_media_failed": "медиа фиристода нашуд",
        "n_label_text": "Матн:",
    },

    # --------------------------------------------------------
    # ҚАЗАҚША (qozoqcha)
    # --------------------------------------------------------
    "kk": {
        "btn_connect": "🔌 Қосу",
        "btn_android": "🤖 Android-та қосу",
        "btn_ios": "🍏 iOS-та қосу",
        "start_caption": (
            "<b>🕵️‍♂️ Қош келдіңіз!</b>\n"
            "Мен сіздің хат-хабарыңызды сіздің орныңызға бақылап отырамын.\n\n"
            "<b>📌 Не істей аламын:</b>\n\n"
            "🔔 Әңгімелесушіңіз хабарламаны <b>өңдесе</b> — ескі мәтінін көрсетемін\n"
            "🗑 Хабарламаны <b>жойса</b> — не жазғанын сақтап қаламын\n"
            "⏳ <b>Бір рет көрілетін</b> фото, видео, дауыстық хабар және дөңгелек видеоларды сақтаймын\n\n"
            "➖➖➖➖➖➖➖➖➖\n\n"
            "<b>⚡️ Баптау — 3 қарапайым қадам:</b>\n\n"
            "1️⃣ Төмендегі <b>«🔌 Қосу»</b> түймесін басыңыз 👇\n\n"
            "2️⃣ Ашылған терезеден <b>«Чат-боттар»</b> бөлімін таңдаңыз 🤖\n\n"
            "3️⃣ Бос өріске бот атын жазыңыз 👇\n"
            "<code>{bot}</code>\n"
            "Төменде бот шығады — <b>оның үстіне басыңыз</b> ✅\n\n"
            "➖➖➖➖➖➖➖➖➖\n\n"
        ),
        "android_caption": (
            "<b>🤖 Android телефонында қосу</b>\n\n"
            "1️⃣ Telegram <b>Параметрлерін</b> ашыңыз ⚙️\n\n"
            "2️⃣ <b>«Менің аккаунтым»</b> бөліміне өтіңіз 👤\n\n"
            "3️⃣ <b>«Чат-боттар»</b> бөлімін таңдаңыз 🤖\n\n"
            "4️⃣ Бос өріске бот атын жазыңыз 👇\n"
            "<code>{bot}</code>\n\n"
            "5️⃣ Төменде шыққан боттың үстіне басыңыз ✅\n\n"
            "<blockquote>💡 Бәрі жоғарыдағы видеода көрсетілген — солай қайталаңыз.</blockquote>"
        ),
        "ios_caption": (
            "<b>🍏 iPhone (iOS) құрылғысында қосу</b>\n\n"
            "1️⃣ Telegram <b>Параметрлерін</b> ашыңыз ⚙️\n\n"
            "2️⃣ <b>«Өңдеу»</b> түймесін басыңыз ✏️\n\n"
            "3️⃣ <b>«Чат-боттар»</b> бөлімін таңдаңыз 🤖\n\n"
            "4️⃣ Бос өріске бот атын жазыңыз 👇\n"
            "<code>{bot}</code>\n\n"
            "5️⃣ Төменде шыққан боттың үстіне басыңыз ✅\n\n"
            "<blockquote>💡 Бәрі жоғарыдағы видеода көрсетілген — солай қайталаңыз.</blockquote>"
        ),
        "connect_caption": (
            "✅ <b>Бот сәтті қосылды</b>\n\n"
            "<b>Қалай пайдалану керек?</b>\n"
            "➖ Егер әңгімелесушіңіз хабарламаны жойса, бот дереу оның көшірмесін сізге жібереді "
            "(тек бот қосылғаннан КЕЙІН жіберілген хабарламалармен жұмыс істейді)\n"
            "➖ Таймерлі (бір рет көрілетін) фото/видеоларды сақтау үшін, сол адаммен диалогта "
            "оларға кез келген хабарламамен жауап беруіңіз керек (видеода ☝️ мысал көрсетілген) "
            "(АШПАС БҰРЫН, БҰЛ МАҢЫЗДЫ!)\n\n"
            "❗ Бот тек қосылғаннан кейін алынған ЖАҢА хабарламалармен жұмыс істейді"
        ),
        "n_edit_title": "✏️ Хабарлама өңделді",
        "n_del_title": "🗑 Хабарлама жойылды",
        "n_label_chat": "💬 Чат:",
        "n_edit_old": "📝 Ескісі:",
        "n_edit_new": "✅ Жаңасы:",
        "n_del_deleted_at": "🕐 Жойылған уақыты:",
        "n_del_sent_at": "🕐 Жіберілген уақыты:",
        "n_media_failed": "медиа жіберілмеді",
        "n_label_text": "Мәтін:",
    },

    # --------------------------------------------------------
    # КЫРГЫЗЧА (qirg'izcha)
    # --------------------------------------------------------
    "ky": {
        "btn_connect": "🔌 Туташтыруу",
        "btn_android": "🤖 Android'де туташтыруу",
        "btn_ios": "🍏 iOS'то туташтыруу",
        "start_caption": (
            "<b>🕵️‍♂️ Кош келиңиз!</b>\n"
            "Мен сиздин жазышууларыңызды сиздин ордуңузга көзөмөлдөп турам.\n\n"
            "<b>📌 Мен эмне кыла алам:</b>\n\n"
            "🔔 Маектешиңиз билдирүүнү <b>оңдосо</b> — эски текстин көрсөтөм\n"
            "🗑 Билдирүүнү <b>өчүрсө</b> — эмне жазганын сактап калам\n"
            "⏳ <b>Бир жолу көрүлүүчү</b> сүрөт, видео, үн билдирүү жана тегерек видеолорду сактайм\n\n"
            "➖➖➖➖➖➖➖➖➖\n\n"
            "<b>⚡️ Жөндөө — 3 жөнөкөй кадам:</b>\n\n"
            "1️⃣ Төмөндөгү <b>«🔌 Туташтыруу»</b> баскычын басыңыз 👇\n\n"
            "2️⃣ Ачылган терезеден <b>«Чат-боттор»</b> бөлүмүн тандаңыз 🤖\n\n"
            "3️⃣ Бош талаага боттун атын жазыңыз 👇\n"
            "<code>{bot}</code>\n"
            "Төмөндө бот чыгат — <b>анын үстүнө басыңыз</b> ✅\n\n"
            "➖➖➖➖➖➖➖➖➖\n\n"
        ),
        "android_caption": (
            "<b>🤖 Android телефондо туташтыруу</b>\n\n"
            "1️⃣ Telegram <b>Жөндөөлөрүн</b> ачыңыз ⚙️\n\n"
            "2️⃣ <b>«Менин аккаунтум»</b> бөлүмүнө өтүңүз 👤\n\n"
            "3️⃣ <b>«Чат-боттор»</b> бөлүмүн тандаңыз 🤖\n\n"
            "4️⃣ Бош талаага боттун атын жазыңыз 👇\n"
            "<code>{bot}</code>\n\n"
            "5️⃣ Төмөндө чыккан боттун үстүнө басыңыз ✅\n\n"
            "<blockquote>💡 Баары жогорудагы видеодо көрсөтүлгөн — ошондой кайталаңыз.</blockquote>"
        ),
        "ios_caption": (
            "<b>🍏 iPhone (iOS) түзмөгүндө туташтыруу</b>\n\n"
            "1️⃣ Telegram <b>Жөндөөлөрүн</b> ачыңыз ⚙️\n\n"
            "2️⃣ <b>«Өзгөртүү»</b> баскычын басыңыз ✏️\n\n"
            "3️⃣ <b>«Чат-боттор»</b> бөлүмүн тандаңыз 🤖\n\n"
            "4️⃣ Бош талаага боттун атын жазыңыз 👇\n"
            "<code>{bot}</code>\n\n"
            "5️⃣ Төмөндө чыккан боттун үстүнө басыңыз ✅\n\n"
            "<blockquote>💡 Баары жогорудагы видеодо көрсөтүлгөн — ошондой кайталаңыз.</blockquote>"
        ),
        "connect_caption": (
            "✅ <b>Бот ийгиликтүү туташты</b>\n\n"
            "<b>Кантип колдонуу керек?</b>\n"
            "➖ Эгер маектешиңиз билдирүүнү өчүрсө, бот дароо анын көчүрмөсүн сизге жөнөтөт "
            "(бот туташкандан КИЙИН жөнөтүлгөн билдирүүлөр менен гана иштейт)\n"
            "➖ Таймерлүү (бир жолу көрүлүүчү) сүрөт/видеолорду сактоо үчүн, ошол адам менен "
            "маекте аларга каалаган билдирүү менен жооп беришиңиз керек (видеодо ☝️ мисал көрсөтүлгөн) "
            "(АЧУУДАН МУРУН, БУЛ МААНИЛҮҮ!)\n\n"
            "❗ Бот туташкандан кийин алынган ЖАҢЫ билдирүүлөр менен гана иштейт"
        ),
        "n_edit_title": "✏️ Билдирүү оңдолду",
        "n_del_title": "🗑 Билдирүү өчүрүлдү",
        "n_label_chat": "💬 Чат:",
        "n_edit_old": "📝 Эскиси:",
        "n_edit_new": "✅ Жаңысы:",
        "n_del_deleted_at": "🕐 Өчүрүлгөн убакыт:",
        "n_del_sent_at": "🕐 Жөнөтүлгөн убакыт:",
        "n_media_failed": "медиа жөнөтүлгөн жок",
        "n_label_text": "Текст:",
    },
}
