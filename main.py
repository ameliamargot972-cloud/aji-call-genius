import os
import io
import logging
from collections import defaultdict

from openai import AsyncOpenAI
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ==============================
# AJI CALL GENIUS CONFIGURATION
# ==============================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("AJI_CALL_GENIUS")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not TELEGRAM_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN environment variable.")

if not OPENAI_API_KEY:
    raise RuntimeError("Missing OPENAI_API_KEY environment variable.")

ai = AsyncOpenAI(api_key=OPENAI_API_KEY)

BOT_NAME = "AJI CALL GENIUS"

# Keep a separate conversation for each user in each chat.
histories = defaultdict(list)

MAX_HISTORY_MESSAGES = 12
MAX_VOICE_SECONDS = 120

SYSTEM_PROMPT = """
You are AJI CALL GENIUS, a helpful multilingual AI assistant.

Your responsibilities:
- Answer questions clearly and accurately.
- Understand and respond to English, Hausa, Chinese, and other languages.
- Translate languages when requested.
- Help with technology, education, coding, and everyday problems.
- Be friendly, respectful, and concise.
- Never claim to have performed an action you did not perform.
- Never claim you can join ordinary Telegram phone calls or live
  group voice chats unless those capabilities are actually implemented.
"""


# ==============================
# START AND HELP COMMANDS
# ==============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        "👋 Welcome to AJI CALL GENIUS!\n\n"
        "🤖 Your personal AI assistant.\n\n"
        "💬 Send me a message to chat with AI.\n"
        "🎙️ Send a voice message and I'll try to understand it.\n"
        "🔊 I can reply with AI-generated audio.\n"
        "🌍 Speak to me in English, Hausa, Chinese, or another language.\n\n"
        "Commands:\n"
        "/start — Start the bot\n"
        "/help — See available features\n"
        "/reset — Clear your conversation history\n"
        "/voice — Generate audio from your next text message\n\n"
        "🚀 Let's talk!"
    )

    await update.effective_message.reply_text(welcome)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "🤖 AJI CALL GENIUS HELP\n\n"
        "💬 Send text to chat with AI.\n"
        "🎙️ Send a Telegram voice message for transcription and an AI reply.\n"
        "🔊 Use /voice to generate audio from your next text message.\n"
        "🌍 Ask for translations in your preferred language.\n"
        "🧹 Use /reset to clear your conversation history.\n\n"
        "Voice calls, live group calls, and paid VIP features "
        "require additional implementation."
    )


async def reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key = (update.effective_chat.id, update.effective_user.id)
    histories.pop(key, None)

    context.user_data["next_reply_as_audio"] = False

    await update.effective_message.reply_text(
        "🧹 Conversation history cleared! Let's start fresh."
    )


async def voice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["next_reply_as_audio"] = True

    await update.effective_message.reply_text(
        "🔊 Audio reply mode activated for your next text message.\n"
        "Send your message now!"
    )


# ==============================
# AI CONVERSATION ENGINE
# ==============================

async def ask_ai(chat_key, user_text):
    history = histories[chat_key]

    history.append({
        "role": "user",
        "content": user_text,
    })

    # Keep recent messages to control context size.
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ] + history[-MAX_HISTORY_MESSAGES:]

    try:
        result = await ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=700,
        )

        answer = result.choices[0].message.content

        if not answer:
            answer = "Sorry, I couldn't generate a response. Try again."

        history.append({
            "role": "assistant",
            "content": answer,
        })

        histories[chat_key] = history[-MAX_HISTORY_MESSAGES:]

        return answer

    except Exception:
        # Remove the failed user message from the saved history.
        if history and history[-1]["content"] == user_text:
            history.pop()

        logger.exception("AI text response failed")
        raise


# ==============================
# TEXT MESSAGE HANDLER
# ==============================

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message

    if not message or not message.text:
        return

    user_text = message.text.strip()

    if not user_text:
        return

    chat_key = (
        update.effective_chat.id,
        update.effective_user.id,
    )

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )

    try:
        answer = await ask_ai(chat_key, user_text)

        if context.user_data.pop("next_reply_as_audio", False):
            await send_ai_audio(update, context, answer)
        else:
            await message.reply_text(
                answer[:4000],
                disable_web_page_preview=True,
            )

    except Exception:
        await message.reply_text(
            "⚠️ I couldn't reach the AI service just now. "
            "Please try again shortly."
        )


# ==============================
# AI-GENERATED AUDIO REPLIES
# ==============================

async def send_ai_audio(update, context, text):
    chat_id = update.effective_chat.id

    try:
        await context.bot.send_chat_action(
            chat_id=chat_id,
            action=ChatAction.UPLOAD_VOICE,
        )

        speech = await ai.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="alloy",
            input=text[:3500],
            response_format="mp3",
        )

        audio_bytes = await speech.aread()

        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "aji_call_genius.mp3"

        await context.bot.send_audio(
            chat_id=chat_id,
            audio=audio_file,
            title="AJI CALL GENIUS AI Reply",
            caption="🔊 AI-generated reply",
        )

    except Exception:
        logger.exception("AI audio generation failed")

        await context.bot.send_message(
            chat_id=chat_id,
            text="I couldn't generate audio this time. "
                 "Please try again later.",
        )


# ==============================
# TELEGRAM VOICE MESSAGE HANDLER
# ==============================

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    voice = message.voice

    if voice.duration > MAX_VOICE_SECONDS:
        await message.reply_text(
            "🎙️ Please send a voice message no longer than "
            f"{MAX_VOICE_SECONDS} seconds."
        )
        return

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=ChatAction.TYPING,
    )

    try:
        telegram_file = await context.bot.get_file(voice.file_id)
        audio_bytes = bytes(await telegram_file.download_as_bytearray())

        transcription = await ai.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=(
                "voice.ogg",
                audio_bytes,
                "audio/ogg",
            ),
        )

        recognized_text = transcription.text.strip()

        if not recognized_text:
            await message.reply_text(
                "I couldn't recognize the words. Please try again."
            )
            return

        chat_key = (
            update.effective_chat.id,
            update.effective_user.id,
        )

        answer = await ask_ai(chat_key, recognized_text)

        await message.reply_text(
            f"🎙️ I understood:\n{recognized_text[:1500]}\n\n"
            f"🤖 {answer[:2200]}"
        )

        # Also send a spoken response.
        await send_ai_audio(update, context, answer)

    except Exception:
        logger.exception("Voice-message processing failed")

        await message.reply_text(
            "⚠️ I couldn't process that voice message. "
            "Please try again with a shorter recording."
        )


# ==============================
# ERROR HANDLER
# ==============================

async def error_handler(update, context):
    logger.error(
        "An unexpected bot error occurred",
        exc_info=context.error,
    )


# ==============================
# START THE BOT
# ==============================

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("reset", reset_command))
    app.add_handler(CommandHandler("voice", voice_command))

    app.add_handler(
        MessageHandler(
            filters.VOICE,
            handle_voice,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text,
        )
    )

    app.add_error_handler(error_handler)

    logger.info("%s is starting...", BOT_NAME)

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
