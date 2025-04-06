import json
from werkzeug.security import generate_password_hash

def add_user_to_json(username, password):
    """Adds a new user with a hashed password to users.json."""
    try:
        with open("users.json", "r") as f:
            users = json.load(f)
    except FileNotFoundError:
        users = {}

    hashed_password = generate_password_hash(password)
    users[username] = {"password": hashed_password}

    with open("users.json", "w") as f:
        json.dump(users, f, indent=2)

    print(f"Hashed password for {username} added to users.json.")


if __name__ == "__main__":
    username = input("Enter username: ")
    password = input("Enter password for {}: ".format(username))
    add_user_to_json(username, password)
    print("User added successfully!")
