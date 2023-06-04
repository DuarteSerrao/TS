#!/usr/bin/env python
from __future__ import print_function, absolute_import, division

import logging
from logging import info, error

# Fuse:
from fusepy import FUSE, FuseOSError, Operations, LoggingMixIn, fuse_get_context
import os
from errno import EACCES
from os.path import realpath
from threading import Lock
import pwd
import grp
import json
from json import JSONDecodeError

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


class Loopback(LoggingMixIn, Operations):
	def __init__(self, root):
		self.root = realpath(root)
		self.rwlock = Lock()

		# Initialize rules (fallback in case of future formatting error)
		try:
			self._load_rules()
		except OSError:
			error("Rule file not found")
			exit(-1)
		except JSONDecodeError:
			error("Rules file badly formatted")
			exit(-2)

		self.received_codes = {}

		bot = telebot.TeleBot("5980867026:AAEx5ukcI67CGPOkD0f-qZK565xrLIhf_2Y")
		self.bot = bot
		bot_thread = Thread(target=self._start_bot)
		bot_thread.start()
		info("Telegram bot started")

		@bot.message_handler(commands=['start'])
		def welcome_message(message):
			user = message.from_user.first_name
			chat_id = message.chat.id
			self.contacts[user] = chat_id

			self._save_rules()
			info(" + " + str((user, chat_id)))
			bot.send_message(chat_id, f"user: {user}\nchat_id: {chat_id}")

		@bot.message_handler(commands=['code'])
		def receive_code(message):
			user = message.from_user.first_name
			code = str(message.text).partition(" ")[2]  # /code lsdhfkhdf
			self.received_codes[user] = code

			info(" c " + str((user, code)))

	def _start_bot(self):
		self.bot.infinity_polling()

	def _send_message(self, user, msg):
		self._load_rules()
		self.bot.send_message(self.contacts[user], msg)

	def _notify_users(self, msg):
		self._load_rules()
		for chat_id in self.contacts.values():
			self.bot.send_message(chat_id, msg)

	def _send_code_and_await(self, user):
		self._load_rules()
		timeout = self.config["timeout"]

		code = _randomword(4)

		self._send_message(user, f"Your code is {code}. Please respond within {timeout} seconds. Format: \"/code {'x'*len(code)}\"")

		start_time = time.time()
		while time.time() - start_time < timeout:  # wait according to the timeout value
			if user not in self.received_codes:
				time.sleep(1)
			elif self.received_codes.get(user) == code:
				del self.received_codes[user]
				return True
			else:
				del self.received_codes[user]
				self._send_message(user, "Wrong code. Aborting")
				return False
		return False

	def _load_rules(self):
		try:
			with open("rules1.json", "r") as f:
				content = json.load(f)
				self.config = content["config"]
				self.contacts = content["contacts"]
				self.rules = content["rules"]
				self.rules.sort(key=lambda rule: rule["priority"], reverse=True)
		except OSError or JSONDecodeError:
			# retain old rules
			pass

	def _save_rules(self):
		with open("rules1.json", "w") as f:
			final = {"config": self.config, "contacts": self.contacts, "rules": self.rules}
			f.write(json.dumps(final, indent=2))

	def _matches(self, user, group, operation, path, match):

		musers = match.get("users")
		mgroups = match.get("groups")
		mops = match.get("operations")
		mpaths = match.get("paths")
		# add more as you see fit

		if musers is not None:
			if user not in musers:
				return False
		if mgroups is not None:
			if group not in mgroups:
				return False
		if mops is not None:
			if operation not in mops:
				return False
		if mpaths is not None:
			if not any(path.startswith(mpath) for mpath in mpaths):
				return False
		return True

	def _find_match(self, user, group, operation, path):
		self._load_rules()

		# return first match
		for rule in self.rules:
			if self._matches(user, group, operation, path, rule["match"]):
				return rule["actions"]

	def __call__(self, op, path, *args):
		user = get_accessing_user()
		group = get_accessing_group()

		# yes, we could make a rule for root, but it would NEED to be in the rule file (fuse uses it), so we just hardcode it
		if user == "root":
			return super(Loopback, self).__call__(op, self.root + path, *args)

		# group system calls in 4 basic permissions (read, write, create, and delete)
		# those that are not here, are not intercepted
		# can be more granular; you do you
		permissions = {
			"create": ["create", "mkdir", "mknod", "link", "symlink"],
			"delete": ["rmdir", "unlink"],
			"read": ["read"],
			"write": ["chmod", "chown", "rename", "write", "truncate"]
		}

		# log read and write attempts (anything else becomes too much)
		if op in ["read", "write"]:
			info(f"{user} {op}{str(args)} \"{path}\"")

		for permission in permissions:
			if op in permissions[permission]:

				actions = self._find_match(user, group, permission, path)
				if actions is None:
					raise FuseOSError(EACCES)

				allow = actions.get("allow")
				notify = actions.get("notify")
				request_auth = actions.get("request_auth")

				# actions in this order:

				if notify is not None:
					self._send_message(notify, f"{user} {op}{str(args)} \"{path}\" ({permission})")

				if not allow:
					raise FuseOSError(EACCES)

				if request_auth is not None:
					if not self._send_code_and_await(request_auth):
						raise FuseOSError(EACCES)

				#break  # operations might have multiple permissions

		return super(Loopback, self).__call__(op, self.root + path, *args)

	# Bellow here, it's basically the same

	def create(self, path, mode, fi=None):
		return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)

	def mkdir(self, path, mode):
		return os.mkdir(path, mode)

	def mknod(self, path, mode, dev):
		return os.mknod(path, mode, dev)

	def link(self, target, source):
		return os.link(self.root + source, target)

	def symlink(self, target, source):
		return os.symlink(source, target)

	def rmdir(self, path):
		return os.rmdir(path)

	def unlink(self, path):
		return os.unlink(path)

	def access(self, path, mode):
		pass  # the check is done in __call__

	def flush(self, path, fh):
		return os.fsync(fh)

	def fsync(self, path, datasync, fh):
		return os.fdatasync(fh) if datasync != 0 else os.fsync(fh)

	def getattr(self, path, fh=None):
		st = os.lstat(path)
		return dict((key, getattr(st, key)) for key in (
			'st_atime', 'st_ctime', 'st_gid', 'st_mode', 'st_mtime',
			'st_nlink', 'st_size', 'st_uid'))

	getxattr = None

	listxattr = None

	def read(self, path, size, offset, fh):
		with self.rwlock:
			os.lseek(fh, offset, 0)
			return os.read(fh, size)

	def readdir(self, path, fh):
		return ['.', '..'] + os.listdir(path)

	def readlink(self, path):
		return os.readlink(path)

	def statfs(self, path):
		stv = os.statvfs(path)
		return dict((key, getattr(stv, key)) for key in (
			'f_bavail', 'f_bfree', 'f_blocks', 'f_bsize', 'f_favail',
			'f_ffree', 'f_files', 'f_flag', 'f_frsize', 'f_namemax'))

	def utimens(self, path, times=None):
		return os.utime(path, times)

	def chmod(self, path, mode):
		return os.chmod(path, mode)

	def chown(self, path, uid, gid):
		return os.chown(path, uid, gid)

	def rename(self, old, new):
		return os.rename(old, self.root + new)

	def write(self, path, data, offset, fh):
		with self.rwlock:
			os.lseek(fh, offset, 0)
			return os.write(fh, data)

	def truncate(self, path, length, fh=None):
		with open(path, 'r+') as f:
			f.truncate(length)

	def open(self, path, flags):
		return os.open(path, flags)

	def release(self, path, fh):
		return os.close(fh)


if __name__ == '__main__':
	import argparse

	parser = argparse.ArgumentParser()
	parser.add_argument('root')
	parser.add_argument('mount')
	args = parser.parse_args()

	logging.basicConfig(level=logging.INFO)
	fuse = FUSE(
		Loopback(args.root), args.mount, foreground=True, allow_other=True)
