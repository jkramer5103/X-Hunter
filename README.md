
# X-Hunter

In X-Hunter, experience the thrill of the chase as players team up to hunt the elusive Mr. X in Real Life! Both Mr. X and the hunters strategically use public transportation to traverse your City.

The game features:

*   Real-time tracking: Mr. X's position updates at set intervals (configurable at game start).
*   Visual interface: Mr. X appears as a red dot, hunters as blue dots.
*   Player identification: Click on a hunter's dot to reveal their name.

Get ready to coordinate, strategize, and outwit Mr. X!

## Quickstart With Docker

```bash
docker pull jkramer5103/x-hunter
```

```bash
docker run --name x-hunter -d -p 1432:1432 jkramer5103/x-hunter:latest
```
The server now runs on port 1432

The Standard Login is:
user: root
password: password

ADD A NEW ADMIN USER AND DELETE THE STANDARD ONE AS SOON AS POSSIBLE

## Installation guide

Clone the project

```bash
git clone https://github.com/jkramer5103/X-Hunter.git
```

Go to the project directory

```bash
cd X-Hunter
```

Install dependencies

```bash
python3 -m pip install -r requirements.txt
```

Create Users (Create new user with username and password)

```bash
python3 create_user.py
```

Start the server

```bash
python3 app.py
```
The server now runs on port 1432

The Standard Login is:
user: root
password: password

ADD A NEW ADMIN USER AND DELETE THE STANDARD ONE AS SOON AS POSSIBLE
