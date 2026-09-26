import asyncio
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from aiogram import Bot

TOKEN = "8785330484:AAH2aXfLWl2xdXpajjjlBXSiE9eeRztWayA"

async def check():
    bot = Bot(token=TOKEN)
    try:
        me = await bot.get_me()
        print(f"BOT_OK: @{me.username} (ID: {me.id}, Имя: {me.full_name})", flush=True)

        # 1. Проверяем канал @persikdlc22
        try:
            ch = await bot.get_chat("@persikdlc22")
            print(f"CHANNEL_OK: '{ch.title}' (ID: {ch.id}, Username: @{ch.username})", flush=True)
            member = await bot.get_chat_member(ch.id, me.id)
            print(f"STATUS_IN_CHANNEL: {member.status}", flush=True)
        except Exception as e:
            print(f"CHANNEL_ERROR: {e}", flush=True)

        # 2. Ищем группу админов в последних апдейтах
        try:
            updates = await bot.get_updates()
            print(f"TOTAL_UPDATES: {len(updates)}", flush=True)
            found_chats = []
            for u in updates:
                chat = None
                if u.message:
                    chat = u.message.chat
                elif u.my_chat_member:
                    chat = u.my_chat_member.chat
                elif u.channel_post:
                    chat = u.channel_post.chat
                
                if chat and (chat.id, chat.title, chat.type) not in found_chats:
                    found_chats.append((chat.id, chat.title, chat.type))
            
            print(f"FOUND_CHATS: {found_chats}", flush=True)
        except Exception as e:
            print(f"UPDATES_ERROR: {e}", flush=True)

    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(check())
