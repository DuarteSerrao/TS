#!/usr/bin/env python
from __future__ import print_function, absolute_import, division

import logging
from logging import info

# Fuse:
from fusepy import FUSE, FuseOSError, Operations, LoggingMixIn, fuse_get_context
import os
from errno import EACCES
from os.path import realpath
from threading import Lock
import pwd
import grp
import json

# Telegram:
import telebot
from threading import Thread
import random
import string
import time

"""
Setup:
sudo pip install fusepy pyTelegramBotAPI
sudo apt install python3-fusepy

Run with:
sudo python3 loopback.py root/ mount/

mount will now have root/ files
"""


def _randomword(length):
	letters_lc = string.ascii_lowercase
	letters_uc = string.ascii_uppercase
	numbers = "0123456789"
	return ''.join(random.choice(numbers) for _ in range(length))


def get_accessing_user():
	uid, _, _ = fuse_get_context()
	return pwd.getpwuid(uid).pw_name


def get_accessing_group():
	_, gid, _ = fuse_get_context()
	return grp.getgrgid(gid).gr_name


def get_flag_slist(flags):
	masks = {
		os.O_CREAT: ["create"],
		os.O_DIRECTORY: ["dir"],
		os.O_RDONLY: ["read"],
		os.O_WRONLY: ["write"],
		os.O_RDWR: ["read", "write"],
	}

	result = []
	for mask in masks:
		if flags & mask == mask:
			for flag in masks[mask]:
				result.append(flag)

	return result


class Loopback(LoggingMixIn, Operations):
	def __init__(self, root):
		self.root = realpath(root)
		self.rwlock = Lock()

		self.cached_chat_id = {}
		self.received_codes = {}

		# Just checking if it's valid
		with open("rules.json") as f:
			self.rules = json.load(f)

		bot = telebot.TeleBot("5980867026:AAEx5ukcI67CGPOkD0f-qZK565xrLIhf_2Y")
		self.bot = bot
		bot_thread = Thread(target=self._start_bot)
		bot_thread.start()
		info("Telegram bot started")

		@bot.message_handler(commands=['start'])
		def welcome_message(message):
			user = message.from_user.first_name
			chat_id = message.chat.id

			self.cached_chat_id[user] = chat_id
			info(" + " + str((user, chat_id)))

			bot.send_message(chat_id, f"user: {user}\nchat_id: {chat_id}")

		@bot.message_handler(commands=['code'])
		def receive_code(message):
			user = message.from_user.first_name
			code = message.text.split(" ")[1]  # /code lsdhfkhdf
			self.received_codes[user] = code

	def _start_bot(self):
		self.bot.infinity_polling()

	def _send_message(self, user, msg):
		self.bot.send_message(self.cached_chat_id[user], msg)

	def _notify_users(self, msg):
		for chat_id in self.cached_chat_id.values():
			self.bot.send_message(chat_id, msg)

	def _send_code_and_await(self, user, code):
		with open("rules.json") as f:
			timeout = json.load(f)["auth_config"]["timeout"]

		self._send_message(user, f"Your code is {code}. Please respond within {timeout} seconds.")

		start_time = time.time()
		while time.time() - start_time < timeout:  # wait according to the timeout value
			if user not in self.received_codes:
				time.sleep(1)
			elif self.received_codes.get(user) == code:
				self.received_codes.pop(user)
				return True
			else:
				self._send_message(user, "Wrong code. Aborting")
				return False
		return False

	def _check_access(self, user, operation, path, root=None):
		if root is None:
			root = self.root

		# Read every time
		with open("rules.json") as f:
			self.rules = json.load(f)["rules"]

		for rule in self.rules:
			if (rule["username"] == user) and \
					operation in rule["operations"] and \
					any(path.startswith(root + p) for p in rule["paths"]):
				return True
		return False
	

	def __call__(self, op, path, *args):
		print(op, path, args)
		return super(Loopback, self).__call__(op, self.root + path, *args)


	# === CREATE ===
	def create(self, path, mode, fi=None):
		if not self._check_access(get_accessing_user(), "create", path):
			raise FuseOSError(EACCES)
		return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
	
	def mkdir(self, path, mode):
		if not self._check_access(get_accessing_user(), "create", path):
			raise FuseOSError(EACCES)
		return os.mkdir(path, mode)
	
	def mknod(self, path, mode):
		if not self._check_access(get_accessing_user(), "create", path):
			raise FuseOSError(EACCES)
		return os.mknod(path, mode)

	def link(self, target, source):
		if not self._check_access(get_accessing_user(), "create", source):
			raise FuseOSError(EACCES)
		return os.link(self.root + source, target)

	def symlink(self, target, source):
		if not self._check_access(get_accessing_user(), "create", source):
			raise FuseOSError(EACCES)
		return os.symlink(source, target)


	# === DELETE ===
	def rmdir(self, path):
		if not self._check_access(get_accessing_user(), "delete", path):
			raise FuseOSError(EACCES)
		return os.rmdir(path)
	
	def unlink(self, path):
		if not self._check_access(get_accessing_user(), "delete", path):
			raise FuseOSError(EACCES)
		return os.unlink(path)


	# === READ ===
	def read(self, path, size, offset, fh):
		if not self._check_access(get_accessing_user(), "read", path):
			raise FuseOSError(EACCES)
		with self.rwlock:
			os.lseek(fh, offset, 0)
			return os.read(fh, size)

	def readdir(self, path, fh):
		if not self._check_access(get_accessing_user(), "read", path):
			raise FuseOSError(EACCES)
		return ['.', '..'] + os.listdir(path)
	
	def readlink(self, path):
		if not self._check_access(get_accessing_user(), "read", path):
			raise FuseOSError(EACCES)
		return os.readlink(path)


	# === WRITE ===
	def chmod(self, path, mode):
		if not self._check_access(get_accessing_user(), "write", path):
			raise FuseOSError(EACCES)
		return os.chmod(path, mode)
	
	def chown(self, path, mode):
		if not self._check_access(get_accessing_user(), "write", path):
			raise FuseOSError(EACCES)
		return os.chown(path, mode)

	def rename(self, old, new):
		if not self._check_access(get_accessing_user(), "write", old, root=""):
			raise FuseOSError(EACCES)
		return os.rename(old, self.root + new)

	def write(self, path, data, offset, fh):
		if not self._check_access(get_accessing_user(), "write", path):
			raise FuseOSError(EACCES)
		with self.rwlock:
			os.lseek(fh, offset, 0)
			return os.write(fh, data)

	def truncate(self, path, length, fh=None):
		if not self._check_access(get_accessing_user(), "write", path):
			raise FuseOSError(EACCES)
		with open(path, 'r+') as f:
			f.truncate(length)












	def access(self, path, mode):
		if not os.access(path, mode):
			raise FuseOSError(EACCES)

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

	listxattr = None

	def open(self, path, flags):
		user = get_accessing_user()
		group = get_accessing_group()

		slflags = get_flag_slist(flags)

		# debug
		self._notify_users(f"User {user} from group {group} is trying to access {path}.\nFlags: {str(slflags)}.")

		# must be allowed to use every flag
		for flag in slflags:
			if not self._check_access(user, flag, path):
				raise FuseOSError(EACCES)

		# allow directly if no cached user to notify (2FA disabled)
		if user not in self.cached_chat_id:
			return os.open(path, flags)

		# sends code and waits for response
		code = _randomword(4)
		if self._send_code_and_await(user, code):
			return os.open(path, flags)

		raise FuseOSError(EACCES)

	def release(self, path, fh):
		return os.close(fh)

	def statfs(self, path):
		stv = os.statvfs(path)
		return dict((key, getattr(stv, key)) for key in (
			'f_bavail', 'f_bfree', 'f_blocks', 'f_bsize', 'f_favail',
			'f_ffree', 'f_files', 'f_flag', 'f_frsize', 'f_namemax'))

	utimens = os.utime




if __name__ == '__main__':
	import argparse

	parser = argparse.ArgumentParser()
	parser.add_argument('root')
	parser.add_argument('mount')
	args = parser.parse_args()

	logging.basicConfig(level=logging.INFO)
	fuse = FUSE(
		Loopback(args.root), args.mount, foreground=True, allow_other=True)
