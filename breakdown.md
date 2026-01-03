# X-Hunter Application Breakdown

## Overview
X-Hunter is a multiplayer web-based game inspired by the classic "Scotland Yard" board game, featuring real-time chat functionality using Flask-SocketIO. The game involves one player acting as Mr. X who tries to evade capture while other players (Seekers) work together to track and catch Mr. X.

## Technology Stack

### Backend Technologies
- **Python 3.11** - Primary programming language
- **Flask** - Web framework for HTTP routing and templating
- **Flask-SocketIO** - WebSocket support for real-time communication
- **eventlet** - Async networking library for WebSocket support
- **simple-websocket** - WebSocket implementation
- **Werkzeug** - Security utilities (password hashing)

### Frontend Technologies
- **HTML5** - Markup language for templates
- **CSS3** - Styling with custom stylesheets
- **JavaScript** - Client-side interactivity
- **Leaflet.js** - Interactive mapping library (v1.9.4)
- **Socket.IO Client** - Real-time client-side communication (v4.7.5)

### Containerization & Deployment
- **Docker** - Containerization using Python 3.11-slim base image
- **Docker Compose** - Multi-container orchestration
- **Coolify** - Deployment platform (mentioned in compose comments)

### Data Storage
- **JSON Files** - Persistent user data storage (`data/users.json`)
- **In-Memory** - Game state storage during runtime
- **File System** - Persistent data directory mounting

## Application Architecture

### Project Structure
```
X-Hunter/
├── app.py                 # Main Flask application (653 lines)
├── requirements.txt       # Python dependencies
├── Dockerfile            # Docker container configuration
├── docker-compose.yml    # Docker Compose setup
├── templates/            # HTML templates (8 files)
│   ├── setup.html       # First-time setup page
│   ├── login_username.html # Username entry
│   ├── login_password.html # Password entry
│   ├── login_setup_password.html # First-time password setup
│   ├── start.html       # Game lobby/admin interface
│   ├── map.html         # Main game interface (848 lines)
│   └── manage_users.html # User management
├── static/
│   └── style.css        # Application styles (219 lines)
└── data/                # Persistent data (created automatically)
    └── users.json       # User database
```

## Core Functionality

### 1. User Management System

#### Authentication Flow
- **Setup Phase**: First-time admin creation without password
- **Login Flow**: Multi-step authentication process
  1. Username entry (`login_username.html`)
  2. Password entry OR password setup (`login_password.html` or `login_setup_password.html`)
- **Session Management**: Flask sessions for user authentication
- **Role-Based Access**: Admin vs regular user permissions

#### User Data Structure
```json
{
  "username": {
    "password": "hashed_password_or_null",
    "has_password": boolean,
    "is_admin": boolean
  }
}
```

#### Admin Features
- Add/delete users
- Grant/revoke admin privileges
- Start/stop games
- Configure game settings

### 2. Game Mechanics

#### Game Roles
- **Mr. X**: The evader who moves through the city
- **Seekers**: Players who work together to catch Mr. X

#### Game Configuration
- **Update Interval**: Time between Mr. X location broadcasts (default: 5 minutes)
- **Decoys**: Number of fake locations Mr. X can place (default: 1)
- **Invisibility**: Number and duration of seeker invisibility uses (default: 2 uses, 30 seconds)

#### Special Abilities
- **Mr. X Decoys**: Place fake locations that are broadcast instead of real position
- **Seeker Invisibility**: Temporarily hide from other seekers and Mr. X

### 3. Real-Time Communication

#### WebSocket Events
- **Connection Management**: Handle player joins/leaves
- **Location Updates**: Real-time position sharing
- **Chat System**: Seeker-only communication
- **Game State**: Start/stop/reset notifications
- **Special Abilities**: Decoy placement and invisibility activation

#### Chat System
- **Seeker-Only**: Mr. X cannot send or receive chat messages
- **Room-Based**: Uses Socket.IO rooms for message broadcasting
- **Real-Time**: Instant message delivery to all seekers

### 4. Mapping & Geolocation

#### Leaflet Integration
- **Interactive Map**: Real-time player position visualization
- **Custom Markers**: Different styles for Mr. X, seekers, decoys
- **Real-Time Updates**: WebSocket-driven position updates
- **User Interaction**: Click-based decoy placement for Mr. X

#### Marker Types
- **Player Markers**: Blue circles for regular seekers
- **Mr. X Marker**: Red circle (only visible at broadcast intervals)
- **Decoy Markers**: Orange dashed circles
- **Real-Time Mr. X**: Green marker for Mr. X's actual position (visible only to Mr. X)

### 5. Game State Management

#### Global Game State
```python
game_state = {
    "active": bool,
    "mr_x": str,
    "update_interval_minutes": int,
    "mr_x_last_broadcast_time": timestamp,
    "mr_x_last_known_location": coordinates,
    "players": dict,
    "mrx_disconnect_task_pending": bool,
    "mrx_total_decoys": int,
    "mrx_remaining_decoys": int,
    "mrx_pending_decoy_location": coordinates,
    "mrx_last_update_was_decoy": bool,
    "seeker_invisibility_uses": int,
    "seeker_invisibility_duration_seconds": int
}
```

#### Player State
```python
players[username] = {
    "sid": str,  # Socket.IO session ID
    "last_location": coordinates,
    "remaining_invisibility": int,
    "invisible_until": timestamp
}
```

### 6. Connection & Disconnect Handling

#### Graceful Disconnect Management
- **Mr. X Grace Period**: 60-second window for reconnection before game ends
- **Player Removal**: Automatic removal of disconnected seekers
- **Background Tasks**: Timer-based grace period enforcement

#### Reconnection Logic
- **Session Preservation**: Maintains player state on reconnection
- **Game Continuity**: Allows seamless rejoining of active games
- **Chat Room Rejoining**: Automatic re-entry into seeker chat room

### 7. Security Features

#### Password Security
- **Werkzeug Hashing**: Secure password storage using `generate_password_hash()`
- **Password Validation**: Minimum 6-character requirement
- **Session Security**: Flask session management

#### Access Control
- **Admin Decorator**: `@admin_required` for protected routes
- **Role Validation**: Admin-only functions for game management
- **Session Validation**: Username verification for WebSocket events

### 8. Docker Configuration

#### Container Setup
- **Base Image**: `python:3.11-slim`
- **Port**: 1432 (internal), mapped by Coolify
- **Volume Mount**: `./data:/app/data` for persistence
- **Environment**: `FLASK_ENV=production`

#### Health & Monitoring
- **Health Checks**: Commented out due to Coolify compatibility issues
- **Restart Policy**: `unless-stopped`
- **Logging**: Container logs for troubleshooting

## Detailed Feature Analysis

### Authentication System

#### Multi-Step Login Process
1. **Username Entry**: User enters username
2. **Password Check**: System determines if user has password set
3. **Route Decision**:
   - If password exists → `login_password.html`
   - If no password → `login_setup_password.html`
4. **Authentication**: Password verification using Werkzeug
5. **Session Creation**: Flask session establishment

#### User Creation Flow
- **Admin Setup**: First user becomes admin automatically
- **User Addition**: Admin can add users without initial passwords
- **Password Setup**: Users set passwords on first login
- **Backward Compatibility**: Migration support for users without passwords

### Game Flow

#### Game Initialization
1. **Admin Configuration**: Select Mr. X, set game parameters
2. **Game State Setup**: Initialize global game state
3. **WebSocket Notification**: Broadcast game start to all clients
4. **Player Registration**: Handle player connections and room assignments

#### Active Gameplay
1. **Location Updates**: Continuous GPS/position tracking
2. **Mr. X Broadcasting**: Periodic location sharing (with decoy support)
3. **Seeker Coordination**: Real-time chat for strategy
4. **Special Abilities**: Decoy placement and invisibility usage
5. **Win Conditions**: Mr. X found or game ends

#### Game Termination
1. **Victory**: Mr. X reports being found
2. **Disconnect**: Mr. X disconnect timeout
3. **Admin Reset**: Manual game termination
4. **State Cleanup**: Reset all game variables

### Real-Time Features

#### WebSocket Event Types
- **Connection Events**: `connect`, `disconnect`
- **Game Events**: `game_started`, `game_over`
- **Player Events**: `player_joined`, `player_left`
- **Location Events**: `update_location`, `location_update`
- **Ability Events**: `set_decoy_location`, `activate_invisibility`
- **Chat Events**: `send_chat_message`, `new_chat_message`

#### Message Broadcasting
- **Selective Broadcasting**: Different messages for different roles
- **Room-Based Messaging**: Seeker chat room isolation
- **Individual Messaging**: Private updates for specific players

### UI/UX Features

#### Responsive Design
- **Mobile Compatibility**: Viewport meta tag and flexible layouts
- **Touch Support**: Mobile-friendly button sizes and interactions
- **Adaptive Layout**: Flexbox-based responsive design

#### Interactive Elements
- **Map Controls**: Zoom, pan, and click interactions
- **Chat Interface**: Toggleable chat panel with message history
- **Action Buttons**: Context-sensitive game controls
- **Status Indicators**: Real-time game state visualization

#### Visual Feedback
- **Connection Status**: Overlay for connection issues
- **Game Over Screen**: Victory/defeat notifications
- **Ability Indicators**: Visual feedback for special abilities
- **Timer Display**: Countdown for Mr. X broadcasts

## Technical Implementation Details

### Flask Application Structure

#### Route Handlers
- **Index (`/`)**: Main game lobby or redirect to setup/login
- **Setup (`/setup`)**: First-time admin creation
- **Login (`/login`)**: Multi-step authentication
- **Map (`/map`)**: Main game interface
- **User Management (`/manage_users`)**: Admin user controls
- **Game Control (`/start_game`)**: Game initialization

#### Decorators & Middleware
- **`@admin_required`**: Route protection for admin functions
- **Session Management**: User authentication state
- **Error Handling**: Flash messages for user feedback

### SocketIO Implementation

#### Event Handlers
- **Connection Management**: Socket registration and room assignment
- **Location Tracking**: Real-time position updates
- **Chat System**: Message routing and broadcasting
- **Game Control**: State synchronization

#### Background Tasks
- **Grace Period Timer**: Mr. X disconnect handling
- **Invisibility Timer**: Seeker visibility restoration
- **Async Operations**: Non-blocking game logic

### Data Persistence

#### User Data Storage
- **JSON Format**: Human-readable user database
- **Atomic Operations**: Safe read/write with error handling
- **Backward Compatibility**: Migration support for schema changes

#### Game State Management
- **In-Memory Storage**: Fast access during gameplay
- **State Reset**: Complete game state cleanup
- **Session Isolation**: Separate game instances

### Security Implementation

#### Authentication Security
- **Password Hashing**: Werkzeug's secure hash functions
- **Session Management**: Flask's secure session handling
- **Input Validation**: Form data sanitization

#### WebSocket Security
- **Session Validation**: Username verification for events
- **Role-Based Access**: Admin-only function protection
- **Message Filtering**: Role-appropriate data distribution

## Performance Considerations

### Scalability
- **Single Instance**: Designed for small group gameplay
- **Memory Usage**: In-memory game state storage
- **Connection Limits**: WebSocket connection management

### Optimization
- **Event-Driven**: Non-blocking I/O with eventlet
- **Selective Updates**: Only send relevant data to clients
- **Efficient Broadcasting**: Room-based message distribution

### Resource Management
- **Background Tasks**: Timer-based cleanup operations
- **Memory Cleanup**: Automatic player removal on disconnect
- **State Reset**: Complete game state cleanup

## Deployment & Operations

### Docker Deployment
- **Container Isolation**: Self-contained application environment
- **Volume Persistence**: Data directory mounting
- **Port Management**: Internal port 1432
- **Environment Configuration**: Production-ready settings

### Monitoring & Logging
- **Application Logs**: Detailed game event logging
- **Error Handling**: Graceful error recovery
- **Connection Monitoring**: WebSocket connection tracking

### Maintenance
- **Data Backup**: JSON file backup procedures
- **User Management**: Admin interface for user operations
- **Game Reset**: Manual and automatic game termination

## Code Quality & Architecture

### Code Organization
- **Modular Design**: Separated concerns (auth, game, chat)
- **Error Handling**: Comprehensive exception management
- **Documentation**: Inline comments and docstrings

### Best Practices
- **Security First**: Proper authentication and authorization
- **Real-Time Design**: WebSocket-based architecture
- **User Experience**: Responsive and interactive interface
- **Maintainability**: Clean code structure and documentation

## Future Enhancement Opportunities

### Technical Improvements
- **Database Integration**: Replace JSON with proper database
- **Load Balancing**: Multi-instance support
- **API Documentation**: OpenAPI/Swagger specification
- **Testing Suite**: Unit and integration tests

### Feature Enhancements
- **Game Statistics**: Historical game data
- **Achievement System**: Player progression
- **Spectator Mode**: Non-player observers
- **Game Variants**: Different game modes and rules

### Performance Optimizations
- **Caching**: Redis for session and game state
- **CDN Integration**: Static asset delivery
- **Database Optimization**: Query performance improvements
- **WebSocket Scaling**: Message queue implementation

This comprehensive breakdown covers every aspect of the X-Hunter application, from its technology stack and architecture to detailed implementation specifics and future improvement possibilities.
