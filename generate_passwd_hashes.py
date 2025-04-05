from werkzeug.security import generate_password_hash
from pyperclip import copy


passwd = input("Enter password: ")
hash = generate_password_hash(passwd)
print(f"Hash got copied into the Clipboard")
copy(hash)