"""Offline database regression tests; uses a temporary SQLite database."""
import asyncio
import os
import shutil
import tempfile
import unittest

TEST_DIR = tempfile.mkdtemp(prefix="telegram_bot_tests_")
os.environ["DATABASE_PATH"] = os.path.join(TEST_DIR, "test.sqlite")

import database  # noqa: E402


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await database.init_db()

    async def test_submission_and_moderation_persist(self):
        sub_id = await database.add_submission(123456, 999, 42, "@test_channel")
        await database.set_admin_message_id(sub_id, 888)
        sub = await database.get_submission(sub_id)
        self.assertIsNotNone(sub)
        self.assertEqual(sub["status"], "pending")
        self.assertEqual(sub["user_id"], 123456)
        self.assertEqual(sub["admin_message_id"], 888)
        await database.update_status(sub_id, "approved", "@admin")
        sub = await database.get_submission(sub_id)
        self.assertEqual(sub["status"], "approved")
        self.assertEqual(sub["moderator_name"], "@admin")

    async def test_ban_and_unban(self):
        await database.ban_user(98765, "Спам", 111)
        ban = await database.get_ban(98765)
        self.assertEqual(ban["reason"], "Спам")
        self.assertTrue(await database.unban_user(98765))
        self.assertIsNone(await database.get_ban(98765))

    async def test_rate_limit_and_rollback(self):
        self.assertEqual(await database.check_and_mark_submission(222, 1000, 60), (True, 0))
        allowed, remaining = await database.check_and_mark_submission(222, 1010, 60)
        self.assertFalse(allowed)
        self.assertGreater(remaining, 0)
        await database.rollback_submission_rate_limit(222, 1000)
        self.assertEqual(await database.check_and_mark_submission(222, 1010, 60), (True, 0))

    async def test_failed_delivery_cleanup_only_removes_pending(self):
        sub_id = await database.add_submission(333, 44)
        await database.delete_pending_submission(sub_id)
        self.assertIsNone(await database.get_submission(sub_id))
        sub_id = await database.add_submission(333, 45)
        await database.update_status(sub_id, "approved", "admin")
        await database.delete_pending_submission(sub_id)
        self.assertEqual((await database.get_submission(sub_id))["status"], "approved")

    async def test_appeal_lifecycle_and_retry(self):
        await database.ban_user(444, "Причина", 1)
        appeal_id = await database.create_appeal_draft(444, 42)
        draft = await database.get_awaiting_appeal(444)
        self.assertEqual(draft["id"], appeal_id)
        await database.submit_appeal(appeal_id, "Прошу пересмотреть")
        appeal = await database.get_appeal(appeal_id)
        self.assertEqual(appeal["status"], "pending")
        await database.reset_appeal_for_retry(appeal_id)
        self.assertEqual((await database.get_appeal(appeal_id))["status"], "awaiting_text")
        await database.submit_appeal(appeal_id, "Повторная апелляция")
        await database.resolve_appeal(appeal_id, "rejected", 777)
        appeal = await database.get_appeal(appeal_id)
        self.assertEqual(appeal["status"], "rejected")
        self.assertEqual(appeal["moderator_id"], 777)


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        shutil.rmtree(TEST_DIR, ignore_errors=True)
