#!/usr/bin/env python
from __future__ import print_function, absolute_import, division

import logging
from logging import info
import os
from errno import EACCES
from os.path import realpath
from threading import Lock

# Fuse:
from fusepy import FUSE, FuseOSError, Operations, LoggingMixIn

# Telegram:
import telebot
from threading import Thread
import random
import string


"""
Setup:
sudo pip install fusepy pyTelegramBotAPI
sudo apt install python3-fusepy

Run with:
sudo python3 loopback.py root/ mount/

mount will now have root/ files
"""


class Loopback(LoggingMixIn, Operations):
    def __init__(self, root):
        self.root = realpath(root)
        self.rwlock = Lock()

        self.cached_chat_id = {}

        bot = telebot.TeleBot("5980867026:AAEx5ukcI67CGPOkD0f-qZK565xrLIhf_2Y")
        self.bot = bot
        bot_thread = Thread(target=self._start_bot)
        bot_thread.start()

        @bot.message_handler(commands=['start'])
        def welcome_message(message):
            if message.chat.type != "private":
                bot.send_message(
                    message.chat.id, "**It's not a good idea to use me on a public chat**")
                return

            user = message.from_user.first_name
            chat_id = message.chat.id

            if user in self.cached_chat_id:
                bot.send_message(chat_id, f"""
					User already cached:
						user_id: {user}
						chat_id: {chat_id}
					"""
                                 )
                return

            self.cached_chat_id[user] = chat_id
            info(" + " + str((user, chat_id)))

            bot.send_message(chat_id, f"""
				I'm a simple bot used to send OTP codes for 2FA. I'm **not interactive**.
				Available commands:
					- /start to cache user entry if not already cached
					- /reset to erase cached user entry
					- /code to request a code (for testing purposes)
	
				Entry added:
					user: {user}
					chat_id: {chat_id}
				"""
                             )

        @bot.message_handler(commands=['reset'])
        def remove_user(message):
            user = message.from_user.first_name
            chat_id = self.cached_chat_id[user]

            self.cached_chat_id.pop(user)
            info(" - " + str((user, chat_id)))

            bot.send_message(message.chat.id, "Entry removed.")

        def _randomword(length):
            letters_lc = string.ascii_lowercase
            letters_uc = string.ascii_uppercase
            numbers = "0123456789"

            return ''.join(random.choice(letters_lc + letters_uc + numbers) for _ in range(length))

        @bot.message_handler(commands=['code'])
        def send_code(message):
            user = message.from_user.first_name
            if user not in self.cached_chat_id:
                self.bot.send_message(
                    message.chat.id, "User not in cache. Use /start.")
                return
            self._send_code(user, _randomword(10))

    def _notify_users(self, path):
        for user, chat_id in self.cached_chat_id.items():
            self.bot.send_message(chat_id, f"File {path} has been opened.")

    def _start_bot(self):
        self.bot.infinity_polling()

    def _send_code(self, user, code):
        self.bot.send_message(self.cached_chat_id[user], code)

    def __call__(self, op, path, *args):
        return super(Loopback, self).__call__(op, self.root + path, *args)

    def access(self, path, mode):
        if not os.access(path, mode):
            raise FuseOSError(EACCES)

    chmod = os.chmod
    chown = os.chown

    def create(self, path, mode, fi=None):
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)

    def flush(self, path, fh):
        return os.fsync(fh)

    def fsync(self, path, datasync, fh):
        if datasync != 0:
            return os.fdatasync(fh)
        else:
            return os.fsync(fh)

    def getattr(self, path, fh=None):
        st = os.lstat(path)
        return dict((key, getattr(st, key)) for key in (
            'st_atime', 'st_ctime', 'st_gid', 'st_mode', 'st_mtime',
            'st_nlink', 'st_size', 'st_uid'))

    getxattr = None

    def link(self, target, source):
        return os.link(self.root + source, target)

    listxattr = None
    mkdir = os.mkdir
    mknod = os.mknod

    def open(self, path, flags):
        self._notify_users(path)
        return os.open(path, flags)

    def read(self, path, size, offset, fh):
        with self.rwlock:
            os.lseek(fh, offset, 0)
            return os.read(fh, size)

    def readdir(self, path, fh):
        return ['.', '..'] + os.listdir(path)

    readlink = os.readlink

    def release(self, path, fh):
        return os.close(fh)

    def rename(self, old, new):
        return os.rename(old, self.root + new)

    rmdir = os.rmdir

    def statfs(self, path):
        stv = os.statvfs(path)
        return dict((key, getattr(stv, key)) for key in (
            'f_bavail', 'f_bfree', 'f_blocks', 'f_bsize', 'f_favail',
            'f_ffree', 'f_files', 'f_flag', 'f_frsize', 'f_namemax'))

    def symlink(self, target, source):
        return os.symlink(source, target)

    def truncate(self, path, length, fh=None):
        with open(path, 'r+') as f:
            f.truncate(length)

    unlink = os.unlink
    utimens = os.utime

    def write(self, path, data, offset, fh):
        with self.rwlock:
            os.lseek(fh, offset, 0)
            return os.write(fh, data)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('root')
    parser.add_argument('mount')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    fuse = FUSE(
        Loopback(args.root), args.mount, foreground=True, allow_other=True)
