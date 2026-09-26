import asyncio
import os
import shutil
import tempfile
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

test_dir = tempfile.mkdtemp()
os.environ["DATABASE_PATH"] = os.path.join(test_dir, "test.sqlite")

import database

async def run_tests():
    print("1. Инициализация БД...")
    await database.init_db()

    print("2. Добавление тестового сообщения в предложку...")
    sub_id = await database.add_submission(
        user_id=123456,
        user_message_id=999
    )
    assert sub_id == 1
    print(f"Заявка создана с ID: {sub_id}")

    print("3. Проверка сохранения ID сообщения в админ группе...")
    await database.set_admin_message_id(sub_id, 888)

    print("4. Проверка получения заявки...")
    sub = await database.get_submission(sub_id)
    assert sub is not None
    assert sub["status"] == "pending"
    assert sub["user_id"] == 123456
    assert sub["user_message_id"] == 999
    assert sub["admin_message_id"] == 888
    print(f"Данные заявки: {sub}")

    print("5. Проверка модерации (Одобрение)...")
    await database.update_status(sub_id, "approved", "@admin_dima")
    updated = await database.get_submission(sub_id)
    assert updated["status"] == "approved"
    assert updated["moderator_name"] == "@admin_dima"
    print(f"Статус успешно обновлен: {updated['status']}, Модератор: {updated['moderator_name']}")

    print("\n✅ Все тесты базы данных успешно пройдены!")

if __name__ == "__main__":
    try:
        asyncio.run(run_tests())
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)
