# Wintermute IRC Bot

An advanced AI-powered IRC bot inspired by William Gibson's Wintermute, featuring dynamic personality adaptation and intelligent conversation management.

## Features

### Core Functionality

- **Dynamic Personality System**: Automatically analyzes channel activity and adapts personality to match community tone.
- **Intelligent Topic Tracking**: Organizes conversations by topic with automatic expiration.
- **Multi-LLM Support**: Primary Anthropic Claude integration with OpenAI fallback.
- **Context-Aware Responses**: Maintains conversation context and references recent discussions.
- **Admin Controls**: Comprehensive management commands for bot configuration.

### Advanced Capabilities

- **Conversation Analysis**: Deep sociolinguistic analysis of channel activity.
- **Automatic Prompt Generation**: Creates tailored personality directives based on channel behavior.
- **Topic Threading**: Groups related messages and maintains conversation flow.
- **User Ignore System**: Flexible user management with persistent ignore lists.
- **Activity Logging**: Comprehensive interaction logging for debugging and analysis.

## Architecture

The bot consists of two main components:

### 1. Wintermute Bot (`wintermute.py`)

The main IRC bot that handles real-time interactions:

- Connects to IRC networks and manages channel presence.
- Processes messages and maintains conversation context.
- Generates responses using Claude (with OpenAI fallback).
- Manages topic threading and user interactions.

### 2. Prompt Generator (`prompt_generator.py`)

Analyzes channel activity and generates dynamic personality directives:

- Processes WeeChat IRC logs for recent activity.
- Performs sociolinguistic analysis of conversations.
- Generates contextual personality directives.
- Archives analysis results for reference.

## Setup

### Prerequisites

- Python 3.7+
- IRC network access
- API keys for Anthropic Claude and OpenAI

### Installation

1.  Clone the repository:

    ```bash
    git clone [https://github.com/yourusername/wintermute-irc-bot.git](https://github.com/yourusername/wintermute-irc-bot.git)
    cd wintermute-irc-bot
    ```

2.  Install dependencies:

    ```bash
    pip install openai anthropic python-dotenv irc
    ```

3.  Create a `.env` file with your configuration:

    ```ini
    # IRC Configuration
    IRC_SERVER=irc.yourserver.org
    IRC_PORT=6667
    IRC_CHANNELS=#yourchannel
    IRC_BOT_NICKNAME=wintermute
    IRC_BOT_PASSWORD=your_bot_password
    IRC_ACCOUNT_NAME=wintermute

    # API Keys
    ANTHROPIC_API_KEY=your_anthropic_api_key
    OPENAI_API_KEY_WINTERMUTE=your_openai_api_key
    OPENAI_API_KEY_PROMPT_GEN=your_openai_api_key_for_analysis
    ```

### Configuration

#### Bot Configuration (`wintermute.py`)

- Modify admin username in the code (search for `adminName`).
- Adjust response parameters and personality settings.
- Configure channel-specific behaviors.

#### Prompt Generator Configuration (`prompt_generator.py`)

- Update `WEECHAT_LOG_FILE_LOCAL_PATH` to point to your IRC logs.
- Set `CHANNEL_NAME_IN_LOG` to match your channel.
- Adjust analysis parameters and token thresholds.

### Usage

#### Running the Bot

```bash
python wintermute.py
```

#### Running Prompt Generation

```bash
python prompt_generator.py
```

For automated personality updates, set up a cron job:

```bash
# Run every hour
0 * * * * /path/to/python /path/to/prompt_generator.py
```

## Bot Commands

### User Commands

- `wintermute: <message>` - Direct conversation with the bot.
- `wintermute: topics` - Show active conversation topics.
- `wintermute: help` - Display available commands.

### Admin Commands (require admin privileges)

- `wintermute: clear topics` - Clear conversation context.
- `wintermute: set system_prompt <text>` - Update bot personality.
- `wintermute: show prompt` - Display current system prompt.
- `wintermute: ignore <user>` - Add user to ignore list.
- `wintermute: unignore <user>` - Remove user from ignore list.
- `wintermute: show ignored` - List ignored users.

## How It Works

### Dynamic Personality System

- **Log Analysis**: Analyzes recent IRC activity using GPT models.
- **Pattern Recognition**: Identifies communication styles, emotional tones, and topics.
- **Directive Generation**: Creates personality instructions tailored to channel culture.
- **Adaptive Response**: Bot behavior automatically adjusts to match community.

### Topic Management

- Messages are automatically categorized by topic using AI.
- Related conversations are grouped together.
- Topics expire after periods of inactivity.
- Context is maintained across topic switches.

### Response Generation

- Primary responses use Anthropic Claude for high-quality conversation.
- OpenAI serves as a fallback for reliability.
- Responses are contextually aware and reference recent discussions.
- The bot maintains a consistent personality while adapting to the conversation flow.

## File Structure

```
wintermute-irc-bot/
├── wintermute.py              # Main bot application
├── prompt_generator.py        # Dynamic personality generator
├── current_bot_directive.json # Current personality directive
├── directive_archive/         # Historical personality directives
├── wintermute_logs.txt        # Bot interaction logs
├── ignore_list.json           # User ignore list
├── archived_summaries.json    # Topic summaries
└── README.md                  # This file
```

## Advanced Features

### Conversation Analysis

The bot performs a deep analysis of channel activity including:

- Overall atmosphere and emotional tones.
- Communication patterns and formality levels.
- Key discussion topics and participant roles.
- Notable moments and memorable quotes.

### Personality Adaptation

- Automatically adjusts to match channel culture.
- References past conversations and user quirks.
- Maintains a core identity while adapting its communication style.
- Preserves community-specific humor and references.

## Contributing

- Fork the repository.
- Create a feature branch.
- Make your changes.
- Submit a pull request.

## License

This project is licensed under the MIT License - see the `LICENSE` file for details.

## Acknowledgments

- Inspired by William Gibson's Wintermute AI from the Sprawl trilogy.
- Built with Anthropic Claude and OpenAI language models.
- Uses the `irc` library for IRC connectivity.

## Support

If you encounter issues or have questions:

- Check the logs in `wintermute_logs.txt`.
- Review the configuration in your `.env` file.
- Open an issue on GitHub with relevant error messages.
