
# X-Hunter - Mr. X Game with Real-time Chat

A multiplayer web-based game inspired by the classic "Scotland Yard" board game, featuring real-time chat functionality using Flask-SocketIO.

## 🎮 Game Overview

X-Hunter is a strategic multiplayer game where:
- **Mr. X** tries to evade capture while moving through the city
- **Seekers** work together to track and catch Mr. X
- **Real-time chat** allows for coordination and strategy discussion
- **WebSocket technology** provides instant updates and communication

## 🚀 Quick Start with Docker

### Prerequisites
- Docker and Docker Compose installed on your system

### 1. Clone and Start
```bash
git clone <repository-url>
cd X-Hunter
docker-compose up -d
```

### 2. First-Time Setup
1. Open your browser and navigate to `http://localhost:1432`
2. You'll be automatically redirected to the **Setup Page**
3. Create your administrator account:
   - Choose a username (min. 3 characters)
   - Set a secure password (min. 6 characters)
   - Confirm your password
4. Click "Admin-Account erstellen"

### 3. Start Playing
1. After setup, you'll be redirected to the login page
2. Login with your admin credentials
3. Add additional users (optional) via the user management
4. Start a new game and enjoy!

## 📁 Project Structure

```
X-Hunter/
├── app.py                 # Main Flask application
├── requirements.txt       # Python dependencies
├── Dockerfile            # Docker container configuration
├── docker-compose.yml    # Docker Compose setup
├── templates/            # HTML templates
│   ├── setup.html       # First-time setup page
│   ├── login.html       # User login
│   ├── start.html       # Game lobby
│   ├── map.html         # Main game interface
│   └── manage_users.html# User management
├── static/
│   └── style.css        # Application styles
└── data/                # Persistent data (created automatically)
    ├── users.db         # SQLite user database
    └── users.json       # Legacy JSON source (auto-migrated if present)
```

## 🛠️ Development Setup

### Local Development
```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python app.py
```

The application will be available at `http://localhost:1432`

### Environment Variables
- `SECRET_KEY`: Flask secret key (defaults to a development key)
- `FLASK_ENV`: Environment mode (development/production)

## Game Features

### Core Gameplay
- **Real-time movement tracking** with WebSocket updates
- **Chat system** for player coordination
- **Admin controls** for game management
- **User management** with role-based permissions
- **Persistent data storage** in SQLite (with legacy JSON auto-migration)

### Admin Features
- Start and stop games
- Manage user accounts
- Configure game settings (decoys, invisibility)
- Monitor active players

### Player Features
- Real-time position updates
- Team chat functionality
- Special abilities (invisibility, decoys)
- Game state synchronization

## 🐳 Docker Configuration

### Services
- **x-hunter-app**: Main application container
- **Port**: 1432 (host:container)
- **Data persistence**: `./data` volume mounted to `/app/data`
- **Health check**: Automated container monitoring

### Volumes
- `./data:/app/data`: Persistent storage for user data and game state

## 🔧 Configuration

### Game Settings (configurable in app.py)
- `MRX_DISCONNECT_GRACE_PERIOD_SECONDS`: Mr. X disconnect timeout
- `DEFAULT_DECOYS`: Number of decoy locations
- `DEFAULT_INVISIBILITY_USES`: Invisibility ability uses
- `DEFAULT_INVISIBILITY_DURATION_SECONDS`: Invisibility duration

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📝 License

This project is open source and available under the [MIT License](LICENSE).

## 🐛 Troubleshooting

### Common Issues

**Port already in use:**
```bash
# Check what's using port 1432
netstat -tulpn | grep :1432
# Or use a different port in docker-compose.yml
```

**Container won't start:**
```bash
# Check logs
docker-compose logs x-hunter-app

# Rebuild container
docker-compose build --no-cache
```

**Setup page not appearing:**
- Ensure the `data/` directory is writable
- Check browser console for JavaScript errors
- Verify no existing `users.db` file (or remove it for a fresh setup)

**Data persistence issues:**
- Ensure the `./data` directory exists on the host
- Check Docker volume permissions
- Verify container has write access to `users.db`

### Getting Help
- Check the application logs: `docker-compose logs -f`
- Review browser developer console for errors
- Ensure all dependencies are properly installed

## 🔄 Updates and Maintenance

### Updating the Application
```bash
# Pull latest changes
git pull

# Rebuild and restart
docker-compose build --no-cache
docker-compose up -d
```

### Backup User Data
```bash
# Backup the data directory
cp -r data/ data_backup/
```

### Reset to Fresh State
```bash
# Stop containers
docker-compose down

# Remove data directory (WARNING: deletes all users)
rm -rf data/

# Restart with fresh setup
docker-compose up -d
```

---

**Enjoy the game! 🎮**
