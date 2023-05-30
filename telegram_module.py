import os
import random
import string

import telebot


"""
Setup:
pip install pyTelegramBotAPI

Run with:
sudo python3 telegram_module.py
"""

bot = telebot.TeleBot("5980867026:AAEx5ukcI67CGPOkD0f-qZK565xrLIhf_2Y")

cached_chat_id = {}


@bot.message_handler(commands=['start'])
def welcome_message(message):
	if message.chat.type != "private":
		bot.send_message(message.chat.id, "**It's not a good idea to use me on a public chat**")
		return

	user = message.from_user.first_name
	chat_id = message.chat.id

	if user in cached_chat_id:
		bot.send_message(chat_id, f"""
			User already cached:
				user_id: {user}
				chat_id: {chat_id}
			"""
		)
		return

	cached_chat_id[user] = chat_id
	print(" + " + str((user, chat_id)))

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
	chat_id = cached_chat_id[user]

	cached_chat_id.pop(user)
	print(" - " + str((user, chat_id)))

	bot.send_message(message.chat.id, "Entry removed.")


def _randomword(length):
	letters_lc = string.ascii_lowercase
	letters_uc = string.ascii_uppercase
	numbers = "0123456789"

	return ''.join(random.choice(letters_lc + letters_uc + numbers) for i in range(length))


def _send_code(user, code):
	bot.send_message(cached_chat_id[user], code, timeout=5)


@bot.message_handler(commands=['code'])
def send_code(message):
	user = message.from_user.first_name
	_send_code(user, _randomword(10))


bot.infinity_polling()
